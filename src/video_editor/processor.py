"""動画編集パイプライン

Veo クリップ → 連結 → BGM → 字幕 → PR表示 までを統合する。
"""

from __future__ import annotations

import random
from pathlib import Path

from config.settings import Settings, get_settings
from src.prompt_generator.models import BgmMood, ContentPlan
from src.utils.logger import get_logger
from src.video_editor.ffmpeg_wrapper import FFmpegWrapper, check_ffmpeg_available
from src.video_editor.pr_overlay import PROverlayBurner
from src.video_editor.subtitle_burner import SubtitleBurner

logger = get_logger(__name__)


class VideoProcessor:
    """動画編集パイプライン"""

    def __init__(
        self,
        settings: Settings | None = None,
        ffmpeg: FFmpegWrapper | None = None,
        subtitle_burner: SubtitleBurner | None = None,
        pr_overlay: PROverlayBurner | None = None,
    ):
        self.settings = settings or get_settings()
        self.ffmpeg = ffmpeg or FFmpegWrapper()
        self.subtitle_burner = subtitle_burner or SubtitleBurner()
        self.pr_overlay = pr_overlay or PROverlayBurner()

    def _pick_bgm(self, mood: BgmMood) -> Path | None:
        """BGM ライブラリから mood に合うファイルをランダム選出"""
        bgm_dir = self.settings.assets_dir / "bgm" / mood
        if not bgm_dir.exists():
            logger.warning("BGM ディレクトリなし", path=str(bgm_dir))
            return None
        candidates = (
            list(bgm_dir.glob("*.mp3"))
            + list(bgm_dir.glob("*.wav"))
            + list(bgm_dir.glob("*.m4a"))
        )
        if not candidates:
            logger.info("BGM ファイル未配置", path=str(bgm_dir))
            return None
        return random.choice(candidates)

    def process(
        self,
        clips: list[Path],
        plan: ContentPlan,
        output_dir: Path | None = None,
        *,
        post_id: str | None = None,
    ) -> Path:
        """フルパイプライン: 連結 → BGM → 字幕 → PR表示"""
        if not clips:
            raise ValueError("クリップが0件です")

        if not check_ffmpeg_available():
            logger.warning("FFmpeg が無いため、編集スキップ。先頭クリップをそのまま返す")
            return clips[0]

        output_dir = output_dir or self.settings.storage_local_dir / "edited"
        output_dir.mkdir(parents=True, exist_ok=True)
        post_id = post_id or "post"

        # 1. 連結
        concat_path = output_dir / f"{post_id}_concat.mp4"
        self.ffmpeg.concat_videos(clips, concat_path)
        current = concat_path

        # 2. BGM 追加(任意)
        bgm = self._pick_bgm(plan.bgm_mood)
        if bgm:
            bgm_path = output_dir / f"{post_id}_with_bgm.mp4"
            try:
                self.ffmpeg.add_bgm(current, bgm, bgm_path)
                current = bgm_path
            except Exception as e:
                logger.warning("BGM追加失敗、スキップ", error=str(e))

        # 3. 字幕焼き込み
        subtitle_path = output_dir / f"{post_id}_subtitled.mp4"
        try:
            self.subtitle_burner.burn(current, subtitle_path, plan.subtitle_text)
            current = subtitle_path
        except Exception as e:
            logger.warning("字幕焼き込み失敗、スキップ", error=str(e))

        # 4. PR表示焼き込み(必須・ステマ規制)
        final_path = output_dir / f"{post_id}_final.mp4"
        try:
            self.pr_overlay.burn(current, final_path, label="広告")
        except Exception as e:
            logger.error("PR表示焼き込み失敗", error=str(e))
            # PR表示は規制対応必須なので失敗時はエラー
            raise

        logger.info("動画編集完了", final=str(final_path))
        return final_path
