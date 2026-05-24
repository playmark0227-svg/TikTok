"""ローカルキャッシュ管理

storage_local/ 配下の古いファイルを自動削除してディスク容量を管理する。
"""

from __future__ import annotations

import time

from config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_RETENTION_DAYS = 7


class LocalCache:
    """ローカル動画ファイルのライフサイクル管理"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def cleanup_old_files(
        self,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        subdirs: list[str] | None = None,
    ) -> int:
        """retention_days を超えたファイルを削除する。

        Returns:
            削除したファイル数
        """
        cutoff_seconds = time.time() - retention_days * 86400
        subdirs = subdirs or ["generated", "edited", "temp", "dry_run_uploads"]
        deleted = 0
        for subdir in subdirs:
            target_dir = self.settings.storage_local_dir / subdir
            if not target_dir.exists():
                continue
            for path in target_dir.iterdir():
                if path.name == ".gitkeep" or path.is_dir():
                    continue
                try:
                    if path.stat().st_mtime < cutoff_seconds:
                        path.unlink()
                        deleted += 1
                except OSError as e:
                    logger.warning("ファイル削除失敗", path=str(path), error=str(e))
        logger.info("ローカルキャッシュ整理", deleted=deleted, retention_days=retention_days)
        return deleted

    def get_size_mb(self) -> float:
        """storage_local/ の合計サイズ(MB)"""
        total = 0
        for path in self.settings.storage_local_dir.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        return total / 1024 / 1024
