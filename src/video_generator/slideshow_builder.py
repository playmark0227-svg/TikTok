"""画像スライドショー動画生成

Veo の代替。商品画像(または生成した画像)から、
Ken Burns効果(ズーム+パン)+ クロスフェード切り替えの 9:16 縦動画を作る。

無料・無限・著作権リスク低・TikTok でよく見るスタイル。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from src.utils.logger import get_logger
from src.video_editor.subtitle_burner import find_default_font

logger = get_logger(__name__)

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920  # 9:16
DEFAULT_FPS = 30
DEFAULT_SLIDE_DURATION = 4.0  # 秒
DEFAULT_TRANSITION_DURATION = 0.5  # 秒


class SlideshowError(Exception):
    """スライドショー生成エラー"""


class SlideshowBuilder:
    """画像から縦長スライドショー動画を生成"""

    def __init__(
        self,
        *,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        fps: int = DEFAULT_FPS,
        slide_duration: float = DEFAULT_SLIDE_DURATION,
        transition_duration: float = DEFAULT_TRANSITION_DURATION,
    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.slide_duration = slide_duration
        self.transition_duration = transition_duration

    def build(
        self,
        image_paths: list[Path],
        output: Path,
        *,
        ken_burns: bool = True,
    ) -> Path:
        """画像リストから動画を生成

        Args:
            image_paths: 入力画像パス
            output: 出力 MP4 パス
            ken_burns: True で各スライドに Ken Burns 効果(ズームイン)

        Returns:
            生成された MP4 のパス
        """
        if not image_paths:
            raise SlideshowError("画像が0件")

        output.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "スライドショー生成開始",
            slide_count=len(image_paths),
            duration_per_slide=self.slide_duration,
            output=str(output),
        )

        # 各画像を「Ken Burns 効果付き短尺クリップ」に変換
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            clip_paths: list[Path] = []
            for i, img_path in enumerate(image_paths):
                clip = tmp_path / f"slide_{i:03d}.mp4"
                self._image_to_clip(img_path, clip, ken_burns=ken_burns, index=i)
                clip_paths.append(clip)

            # 連結(クロスフェード付き)
            if len(clip_paths) == 1:
                shutil.copyfile(clip_paths[0], output)
            else:
                self._concat_with_xfade(clip_paths, output)

        logger.info("スライドショー生成完了", path=str(output), size=output.stat().st_size)
        return output

    def _image_to_clip(
        self,
        image: Path,
        output: Path,
        *,
        ken_burns: bool,
        index: int,
    ) -> Path:
        """1枚の画像を短尺動画化"""
        if not image.exists():
            raise SlideshowError(f"画像が存在しません: {image}")

        # 入力画像を 1080x1920 にフィット(crop または pad)
        # cover でフィット(画像をズームしてフレームを満たす、はみ出しは切る)
        cover_filter = (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
            f"crop={self.width}:{self.height}"
        )

        if ken_burns:
            # ズームイン or ズームアウトを交互に
            zoom_in = index % 2 == 0
            total_frames = int(self.slide_duration * self.fps)
            if zoom_in:
                # 1.0 → 1.15 に拡大
                zoom_expr = f"min(zoom+0.0015,1.15)"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"
            else:
                # 1.15 → 1.0 に縮小
                zoom_expr = f"if(eq(on,0),1.15,max(zoom-0.0015,1.0))"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"

            zoompan = (
                f"zoompan=z='{zoom_expr}':d={total_frames}:"
                f"x='{x_expr}':y='{y_expr}':"
                f"s={self.width}x{self.height}:fps={self.fps}"
            )
            vf = f"{cover_filter},{zoompan}"
        else:
            vf = cover_filter

        cmd = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", str(image),
            "-vf", vf,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-t", str(self.slide_duration),
            "-r", str(self.fps),
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Ken Burns ffmpeg エラー", stderr=result.stderr[-500:])
            raise SlideshowError(f"スライド変換失敗: {result.stderr[-200:]}")
        return output

    def _concat_with_xfade(self, clips: list[Path], output: Path) -> Path:
        """クロスフェード付きで連結"""
        # filter_complex で xfade を連鎖
        # [0][1]xfade=transition=fade:duration=0.5:offset=3.5[v1]
        # [v1][2]xfade=transition=fade:duration=0.5:offset=7[v2]
        # ...

        inputs: list[str] = []
        for clip in clips:
            inputs.extend(["-i", str(clip)])

        # 最後のクリップは長さ通り、それ以前は overlap 分を引いた位置で次が始まる
        n = len(clips)
        filter_lines: list[str] = []
        last_label = "[0:v]"
        cumulative_offset = self.slide_duration - self.transition_duration

        for i in range(1, n):
            cur_label = f"[v{i}]"
            offset = cumulative_offset
            filter_lines.append(
                f"{last_label}[{i}:v]xfade=transition=fade:"
                f"duration={self.transition_duration}:offset={offset}{cur_label}"
            )
            last_label = cur_label
            cumulative_offset += self.slide_duration - self.transition_duration

        filter_complex = ";".join(filter_lines)
        cmd = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", last_label,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-r", str(self.fps),
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("xfade ffmpeg エラー", stderr=result.stderr[-500:])
            raise SlideshowError(f"クロスフェード連結失敗: {result.stderr[-200:]}")
        return output


def generate_placeholder_image(
    output: Path,
    title: str,
    subtitle: str = "",
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    bg_color: tuple[int, int, int] = (30, 41, 59),  # slate-800
    accent_color: tuple[int, int, int] = (236, 72, 153),  # pink-500
    text_color: tuple[int, int, int] = (248, 250, 252),  # slate-50
) -> Path:
    """画像生成 API が使えない場合の代替: テキスト入り単色画像

    商品画像が無い時のスライド素材として。
    """
    from PIL import Image, ImageDraw, ImageFont

    output.parent.mkdir(parents=True, exist_ok=True)

    # グラデーション背景
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # 上から下へグラデーション
    for y in range(height):
        ratio = y / height
        r = int(bg_color[0] + (accent_color[0] - bg_color[0]) * ratio * 0.3)
        g = int(bg_color[1] + (accent_color[1] - bg_color[1]) * ratio * 0.3)
        b = int(bg_color[2] + (accent_color[2] - bg_color[2]) * ratio * 0.3)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # アクセントバー(左上)
    draw.rectangle([0, 0, 12, height], fill=accent_color)

    # フォント
    font_path = find_default_font()
    title_size = int(width * 0.075)
    subtitle_size = int(width * 0.045)

    try:
        title_font = (
            ImageFont.truetype(str(font_path), title_size)
            if font_path
            else ImageFont.load_default()
        )
        subtitle_font = (
            ImageFont.truetype(str(font_path), subtitle_size)
            if font_path
            else ImageFont.load_default()
        )
    except Exception:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()

    # タイトルを中央に折り返して描画
    padding = int(width * 0.08)
    max_chars_per_line = 14
    title_lines = _wrap_text(title, max_chars_per_line)

    line_height = int(title_size * 1.3)
    total_text_height = line_height * len(title_lines)
    if subtitle:
        total_text_height += int(subtitle_size * 1.5) + int(width * 0.04)

    y_start = (height - total_text_height) // 2

    for i, line in enumerate(title_lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        y = y_start + i * line_height
        # 影
        draw.text((x + 3, y + 3), line, font=title_font, fill=(0, 0, 0, 128))
        # 本文
        draw.text((x, y), line, font=title_font, fill=text_color)

    if subtitle:
        y_sub = y_start + len(title_lines) * line_height + int(width * 0.04)
        sub_lines = _wrap_text(subtitle, max_chars_per_line + 4)
        for i, line in enumerate(sub_lines):
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            text_width = bbox[2] - bbox[0]
            x = (width - text_width) // 2
            y = y_sub + i * int(subtitle_size * 1.3)
            draw.text((x, y), line, font=subtitle_font, fill=accent_color)

    img.save(output, "PNG")
    return output


def _wrap_text(text: str, max_chars: int) -> list[str]:
    """日本語向けの簡易折り返し(文字数ベース)"""
    if len(text) <= max_chars:
        return [text]
    lines: list[str] = []
    current = ""
    for ch in text:
        current += ch
        if len(current) >= max_chars:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return lines
