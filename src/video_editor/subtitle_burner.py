"""字幕焼き込み

drawtext フィルタで日本語字幕を動画下部に焼き込む。
複数行は時間差で順次表示。
"""

from __future__ import annotations

import platform
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

# プラットフォーム別フォントパス候補
DEFAULT_FONT_CANDIDATES = {
    "Darwin": [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ],
    "Linux": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ],
    "Windows": [
        "C:/Windows/Fonts/YuGothB.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
    ],
}


def find_default_font() -> Path | None:
    """OS に応じたデフォルトフォントを探す"""
    candidates = DEFAULT_FONT_CANDIDATES.get(platform.system(), [])
    for path_str in candidates:
        path = Path(path_str)
        if path.exists():
            return path
    return None


class SubtitleBurner:
    """字幕焼き込み"""

    def __init__(self, font_path: Path | None = None):
        self.font_path = font_path or find_default_font()
        if self.font_path is None:
            logger.warning("デフォルトフォントが見つかりません。字幕表示が崩れる可能性があります")

    def burn(
        self,
        video: Path,
        output: Path,
        subtitle_text: str,
        *,
        font_size: int = 56,
        font_color: str = "white",
        outline_color: str = "black",
        outline_width: int = 4,
        line_duration: float = 2.0,
        bottom_margin: int = 180,
    ) -> Path:
        """字幕を焼き込む

        Args:
            subtitle_text: 改行区切りの字幕(各行が時間差で表示される)
            line_duration: 1行あたりの表示秒数
        """
        try:
            import ffmpeg  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError("ffmpeg-python がインストールされていません") from e

        output.parent.mkdir(parents=True, exist_ok=True)
        lines = [line.strip() for line in subtitle_text.split("\n") if line.strip()]
        if not lines:
            logger.info("字幕テキストなし、コピーのみ実行")
            import shutil

            shutil.copyfile(video, output)
            return output

        logger.info(
            "字幕焼き込み",
            lines=len(lines),
            font_size=font_size,
            video=str(video),
        )

        input_stream = ffmpeg.input(str(video))
        v = input_stream.video
        a = input_stream.audio

        for i, line in enumerate(lines):
            start = i * line_duration
            end = start + line_duration
            v = self._apply_drawtext(
                v,
                line,
                start=start,
                end=end,
                font_size=font_size,
                font_color=font_color,
                outline_color=outline_color,
                outline_width=outline_width,
                bottom_margin=bottom_margin,
            )

        try:
            (
                ffmpeg.output(
                    v,
                    a,
                    str(output),
                    vcodec="libx264",
                    acodec="copy",
                    pix_fmt="yuv420p",
                    movflags="+faststart",
                )
                .overwrite_output()
                .run(quiet=True)
            )
        except ffmpeg.Error as e:
            # 音声なしの場合
            logger.warning("音声付き書き出し失敗、無音で再試行", error=str(e))
            (
                ffmpeg.output(
                    v,
                    str(output),
                    vcodec="libx264",
                    pix_fmt="yuv420p",
                    movflags="+faststart",
                )
                .overwrite_output()
                .run(quiet=True)
            )

        return output

    def _apply_drawtext(
        self,
        v_stream,
        text: str,
        *,
        start: float,
        end: float,
        font_size: int,
        font_color: str,
        outline_color: str,
        outline_width: int,
        bottom_margin: int,
    ):
        kwargs = {
            "text": self._escape_drawtext(text),
            "fontsize": font_size,
            "fontcolor": font_color,
            "borderw": outline_width,
            "bordercolor": outline_color,
            "x": "(w-text_w)/2",
            "y": f"h-{bottom_margin}",
            "enable": f"between(t,{start},{end})",
        }
        if self.font_path:
            kwargs["fontfile"] = str(self.font_path)
        return v_stream.drawtext(**kwargs)

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        """drawtext フィルタ用に特殊文字をエスケープ"""
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
