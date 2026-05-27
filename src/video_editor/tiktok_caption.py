"""TikTok 風テロップ焼き込み

通常の SubtitleBurner より目立つスタイル:
- 大きめのフォント(動画幅の8%)
- 半透明黒の角丸ボックス背景
- 行ごとに色を変える(白/黄色/ピンク)
- 太い縁取り
- 画面下 1/4 に配置
- 行ごとに表示時間をずらす
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.utils.logger import get_logger
from src.utils.text import strip_emoji
from src.video_editor.subtitle_burner import find_default_font

logger = get_logger(__name__)

# TikTok でよく見るアクセントカラー(行ごとにローテーション)
LINE_COLORS = [
    ("white", "black"),       # 白文字 + 黒縁
    ("yellow", "black"),      # 黄文字 + 黒縁(目立つ)
    ("hotpink", "black"),     # ピンク + 黒縁(可愛い系)
    ("cyan", "black"),        # シアン + 黒縁(冷たい系)
]


def _escape_drawtext(text: str) -> str:
    """drawtext の特殊文字をエスケープ"""
    return (
        text.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace(",", r"\,")
        .replace(";", r"\;")
        .replace("%", r"\%")
    )


class TikTokCaptionBurner:
    """TikTok 風テロップ焼き込み"""

    def __init__(self, font_path: Path | None = None):
        self.font_path = font_path or find_default_font()
        if self.font_path is None:
            logger.warning("日本語フォント未検出、文字化けの可能性あり")

    def burn(
        self,
        video: Path,
        output: Path,
        subtitle_text: str,
        *,
        font_size_ratio: float = 0.075,
        line_duration: float = 2.5,
        bottom_ratio: float = 0.25,
        outline_width: int = 6,
        box_padding: int = 16,
    ) -> Path:
        """字幕を TikTok 風に焼き込む

        Args:
            font_size_ratio: 動画幅に対するフォントサイズ比率(0.075 = 7.5%)
            line_duration: 1行あたりの表示秒数
            bottom_ratio: 下からの位置比率(0.25 = 画面下から 25%)
        """
        output.parent.mkdir(parents=True, exist_ok=True)
        # 絵文字は焼き込めない(豆腐文字になる)ので除去
        cleaned = strip_emoji(subtitle_text)
        lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
        if not lines:
            import shutil
            shutil.copyfile(video, output)
            return output

        # 動画幅取得(1080 想定だが ffprobe で確認)
        width = self._get_video_width(video)
        font_size = int(width * font_size_ratio)

        # filter chain を組み立て
        drawtexts: list[str] = []
        for i, line in enumerate(lines):
            color_fg, color_outline = LINE_COLORS[i % len(LINE_COLORS)]
            start = i * line_duration
            end = start + line_duration + 0.3  # フェードアウトに余裕
            escaped = _escape_drawtext(line)

            drawtext_args = [
                f"text='{escaped}'",
                f"fontsize={font_size}",
                f"fontcolor={color_fg}",
                f"borderw={outline_width}",
                f"bordercolor={color_outline}",
                "box=1",
                "boxcolor=black@0.55",
                f"boxborderw={box_padding}",
                "x=(w-text_w)/2",
                f"y=h-h*{bottom_ratio}-text_h/2",
                f"enable='between(t,{start},{end})'",
            ]
            if self.font_path:
                drawtext_args.append(f"fontfile={self.font_path}")
            drawtexts.append(f"drawtext={':'.join(drawtext_args)}")

        vf = ",".join(drawtexts)

        # FFmpeg 実行
        cmd_video = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-vf", vf,
            "-c:v", "libx264",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output),
        ]
        result = subprocess.run(cmd_video, capture_output=True, text=True)
        if result.returncode != 0:
            # 音声 copy がダメな場合は再エンコ
            logger.warning("字幕焼き込み再試行(音声再エンコ)", stderr=result.stderr[-300:])
            cmd_video[cmd_video.index("-c:a") + 1] = "aac"
            result = subprocess.run(cmd_video, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("字幕焼き込み失敗", stderr=result.stderr[-500:])
                raise RuntimeError(f"字幕焼き込み失敗: {result.stderr[-200:]}")

        return output

    def _get_video_width(self, video: Path) -> int:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width",
                    "-of", "csv=p=0",
                    str(video),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return int(result.stdout.strip())
        except Exception:
            return 1080
