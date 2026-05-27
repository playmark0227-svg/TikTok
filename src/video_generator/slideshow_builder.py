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
from src.utils.text import strip_emoji
from src.video_editor.subtitle_burner import find_default_font
from src.video_generator.effects import pick_effect, pick_transition

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
        """1枚の画像を短尺動画化(無音オーディオトラック付き)"""
        if not image.exists():
            raise SlideshowError(f"画像が存在しません: {image}")

        # 入力画像を 1080x1920 にフィット(crop または pad)
        cover_filter = (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
            f"crop={self.width}:{self.height}"
        )

        if ken_burns:
            # 多様なエフェクト(slide index でローテーション)
            effect = pick_effect(index)
            vf = effect.vf_builder(self.width, self.height, self.slide_duration, self.fps)
            logger.debug("エフェクト適用", index=index, effect=effect.name)
        else:
            vf = cover_filter

        # 無音オーディオを生成して結合 (TikTok アップロード互換性のため)
        cmd = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", str(image),
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", vf,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
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
        """クロスフェード付きで連結(映像 + 音声両方)"""
        inputs: list[str] = []
        for clip in clips:
            inputs.extend(["-i", str(clip)])

        n = len(clips)
        filter_lines: list[str] = []
        video_label = "[0:v]"
        audio_label = "[0:a]"
        cumulative_offset = self.slide_duration - self.transition_duration

        for i in range(1, n):
            v_out = f"[v{i}]"
            a_out = f"[a{i}]"
            offset = cumulative_offset
            transition = pick_transition(i - 1)
            filter_lines.append(
                f"{video_label}[{i}:v]xfade=transition={transition}:"
                f"duration={self.transition_duration}:offset={offset}{v_out}"
            )
            filter_lines.append(
                f"{audio_label}[{i}:a]acrossfade="
                f"duration={self.transition_duration}{a_out}"
            )
            video_label = v_out
            audio_label = a_out
            cumulative_offset += self.slide_duration - self.transition_duration

        filter_complex = ";".join(filter_lines)
        cmd = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", video_label,
            "-map", audio_label,
            "-c:v", "libx264",
            "-c:a", "aac",
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


# スライドのカラーパレット(index でローテーション)
PALETTES = [
    # (背景上, 背景下, アクセント, テキスト)
    ((15, 23, 42), (88, 28, 135), (236, 72, 153), (248, 250, 252)),   # 紺→紫 + ピンク
    ((30, 58, 138), (37, 99, 235), (251, 191, 36), (255, 255, 255)),  # 青グラデ + イエロー
    ((6, 78, 59), (5, 150, 105), (251, 113, 133), (240, 253, 244)),   # 深緑→緑 + ローズ
    ((127, 29, 29), (220, 38, 38), (250, 204, 21), (255, 251, 235)),  # 赤グラデ + 黄
    ((76, 29, 149), (139, 92, 246), (34, 211, 238), (245, 243, 255)), # 紫グラデ + シアン
    ((17, 24, 39), (55, 65, 81), (16, 185, 129), (243, 244, 246)),    # ダークグレー + 緑
]


def generate_placeholder_image(
    output: Path,
    title: str,
    subtitle: str = "",
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    palette_index: int = 0,
) -> Path:
    """画像生成 API が使えない場合の代替: テキスト入り装飾画像

    商品画像が無い時のスライド素材として。
    palette_index でカラーパレットをローテーション。
    """
    from PIL import Image, ImageDraw, ImageFont

    output.parent.mkdir(parents=True, exist_ok=True)

    # 絵文字は描画できないので除去
    title = strip_emoji(title)
    subtitle = strip_emoji(subtitle)

    palette = PALETTES[palette_index % len(PALETTES)]
    bg_top, bg_bottom, accent_color, text_color = palette

    img = Image.new("RGB", (width, height), bg_top)
    draw = ImageDraw.Draw(img)

    # 縦グラデーション(滑らかに上→下)
    for y in range(height):
        ratio = y / height
        r = int(bg_top[0] + (bg_bottom[0] - bg_top[0]) * ratio)
        g = int(bg_top[1] + (bg_bottom[1] - bg_top[1]) * ratio)
        b = int(bg_top[2] + (bg_bottom[2] - bg_top[2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 装飾: 右上に大きな円(半透明風、塗りつぶし)
    circle_size = int(width * 0.5)
    circle_x = width - int(circle_size * 0.3)
    circle_y = -int(circle_size * 0.3)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.ellipse(
        [circle_x, circle_y, circle_x + circle_size, circle_y + circle_size],
        fill=(*accent_color, 60),
    )
    # 左下に小さな円
    overlay_draw.ellipse(
        [-100, height - 250, 300, height + 50],
        fill=(*accent_color, 40),
    )
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # 左サイドのアクセントバー
    draw.rectangle([0, 0, 16, height], fill=accent_color)

    # フォント
    font_path = find_default_font()
    title_size = int(width * 0.085)
    subtitle_size = int(width * 0.040)

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

    # タイトル中央配置(折り返し対応)
    max_chars_per_line = 12
    title_lines = _wrap_text(title, max_chars_per_line)

    line_height = int(title_size * 1.25)
    total_text_height = line_height * len(title_lines)
    if subtitle:
        total_text_height += int(subtitle_size * 1.4) + int(width * 0.05)

    # 画面の上 1/3 〜 中央寄りに配置(下部に字幕を残すスペース)
    y_start = int(height * 0.35) - total_text_height // 2

    for i, line in enumerate(title_lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        y = y_start + i * line_height
        # 影(深く・ボケた感じを2重で出す)
        for ox, oy in [(4, 4), (2, 2)]:
            draw.text((x + ox, y + oy), line, font=title_font, fill=(0, 0, 0))
        # 本文
        draw.text((x, y), line, font=title_font, fill=text_color)

    if subtitle:
        y_sub = y_start + len(title_lines) * line_height + int(width * 0.05)
        sub_lines = _wrap_text(subtitle, max_chars_per_line + 6)
        for i, line in enumerate(sub_lines):
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            text_width = bbox[2] - bbox[0]
            x = (width - text_width) // 2
            y = y_sub + i * int(subtitle_size * 1.35)
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
