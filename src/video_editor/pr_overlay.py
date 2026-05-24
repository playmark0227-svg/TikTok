"""PR / 広告表示オーバーレイ

ステマ規制(景品表示法)対応のため、動画全長で「広告」表示を画面右上に焼き込む。
"""

from __future__ import annotations

from pathlib import Path

from src.utils.logger import get_logger
from src.video_editor.subtitle_burner import find_default_font

logger = get_logger(__name__)


class PROverlayBurner:
    """PR/広告ラベルのオーバーレイ"""

    def __init__(self, font_path: Path | None = None):
        self.font_path = font_path or find_default_font()

    def burn(
        self,
        video: Path,
        output: Path,
        *,
        label: str = "広告",
        font_size_ratio: float = 0.04,
        padding: int = 16,
        bg_color: str = "black@0.6",
        font_color: str = "white",
    ) -> Path:
        """画面右上に「広告」表示を焼き込む

        Args:
            label: 表示する文字列 ("広告" / "PR" / "AD" など)
            font_size_ratio: 動画幅に対するフォントサイズの比率
            padding: 余白(ピクセル)
        """
        try:
            import ffmpeg  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError("ffmpeg-python がインストールされていません") from e

        output.parent.mkdir(parents=True, exist_ok=True)
        logger.info("PR表示焼き込み", label=label, video=str(video))

        # 9:16 (1080x1920) を想定して font_size を計算
        # font_size = w * ratio として ffmpeg 内で計算させる
        font_size_expr = f"{int(1080 * font_size_ratio)}"

        input_stream = ffmpeg.input(str(video))
        v = input_stream.video

        drawtext_kwargs = {
            "text": label,
            "fontsize": font_size_expr,
            "fontcolor": font_color,
            "box": 1,
            "boxcolor": bg_color,
            "boxborderw": padding // 2,
            "x": f"w-text_w-{padding}",
            "y": f"{padding}",
        }
        if self.font_path:
            drawtext_kwargs["fontfile"] = str(self.font_path)

        v = v.drawtext(**drawtext_kwargs)

        try:
            (
                ffmpeg.output(
                    v,
                    input_stream.audio,
                    str(output),
                    vcodec="libx264",
                    acodec="copy",
                    pix_fmt="yuv420p",
                    movflags="+faststart",
                )
                .overwrite_output()
                .run(quiet=True)
            )
        except ffmpeg.Error:
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
