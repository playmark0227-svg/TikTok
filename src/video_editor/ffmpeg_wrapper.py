"""FFmpeg ラッパー

ffmpeg-python を使用して、動画の連結・BGM追加・字幕焼き込み・PR表示を行う。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)


class FFmpegError(Exception):
    """FFmpeg 実行エラー"""


def check_ffmpeg_available() -> bool:
    """ffmpeg コマンドが PATH に存在するか"""
    return shutil.which("ffmpeg") is not None


class FFmpegWrapper:
    """FFmpeg 操作ラッパー"""

    def __init__(self, *, video_codec: str = "libx264", audio_codec: str = "aac"):
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        if not check_ffmpeg_available():
            logger.warning("ffmpeg コマンドが見つかりません。動画編集機能は動作しません")

    def concat_videos(self, clips: list[Path], output: Path) -> Path:
        """複数クリップを連結"""
        if not clips:
            raise FFmpegError("連結するクリップがありません")
        if len(clips) == 1:
            shutil.copyfile(clips[0], output)
            return output

        try:
            import ffmpeg  # type: ignore[import-untyped]
        except ImportError as e:
            raise FFmpegError("ffmpeg-python がインストールされていません") from e

        output.parent.mkdir(parents=True, exist_ok=True)
        logger.info("動画連結", clips=[str(c) for c in clips], output=str(output))

        # concat demuxer 方式(再エンコード不要)を試みる
        list_file = output.parent / f".concat_{output.stem}.txt"
        try:
            with open(list_file, "w", encoding="utf-8") as f:
                for clip in clips:
                    f.write(f"file '{clip.resolve()}'\n")

            try:
                (
                    ffmpeg.input(str(list_file), format="concat", safe=0)
                    .output(str(output), c="copy", movflags="+faststart")
                    .overwrite_output()
                    .run(quiet=True)
                )
            except ffmpeg.Error:
                # フォールバック: 再エンコード
                logger.warning("concat demuxer 失敗、再エンコードで再試行")
                inputs = [ffmpeg.input(str(c)) for c in clips]
                streams = []
                for inp in inputs:
                    streams.append(inp.video)
                    streams.append(inp.audio)
                joined = ffmpeg.concat(*streams, v=1, a=1).node
                v_out = joined[0]
                a_out = joined[1]
                (
                    ffmpeg.output(
                        v_out,
                        a_out,
                        str(output),
                        vcodec=self.video_codec,
                        acodec=self.audio_codec,
                        pix_fmt="yuv420p",
                        movflags="+faststart",
                    )
                    .overwrite_output()
                    .run(quiet=True)
                )
        finally:
            if list_file.exists():
                list_file.unlink()

        return output

    def add_bgm(
        self,
        video: Path,
        bgm: Path,
        output: Path,
        *,
        bgm_volume: float = 0.15,
        original_volume: float = 1.0,
    ) -> Path:
        """BGM をオリジナル音声にミックス"""
        try:
            import ffmpeg  # type: ignore[import-untyped]
        except ImportError as e:
            raise FFmpegError("ffmpeg-python がインストールされていません") from e

        output.parent.mkdir(parents=True, exist_ok=True)
        logger.info("BGM追加", video=str(video), bgm=str(bgm), volume=bgm_volume)

        in_video = ffmpeg.input(str(video))
        in_bgm = ffmpeg.input(str(bgm))

        # 動画長に BGM を合わせる
        bgm_audio = in_bgm.audio.filter("volume", bgm_volume).filter(
            "apad"
        )  # 短ければループ用にパディング

        try:
            video_audio = in_video.audio.filter("volume", original_volume)
            mixed = ffmpeg.filter(
                [video_audio, bgm_audio],
                "amix",
                inputs=2,
                duration="first",
                dropout_transition=2,
            )
        except Exception:
            # 元動画に音声が無い場合
            mixed = bgm_audio

        (
            ffmpeg.output(
                in_video.video,
                mixed,
                str(output),
                vcodec="copy",
                acodec=self.audio_codec,
                shortest=None,
                movflags="+faststart",
            )
            .overwrite_output()
            .run(quiet=True)
        )
        return output

    def get_duration(self, video: Path) -> float:
        """動画の長さ(秒)を取得"""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError) as e:
            raise FFmpegError(f"動画長取得失敗: {e}") from e
