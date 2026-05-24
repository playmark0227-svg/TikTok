"""エントリポイント

毎日17:00に launchd から起動され、パイプラインを実行する。
Phase 0 ではスタブのみ。Phase 7 で Orchestrator を統合。
"""

from __future__ import annotations

import asyncio
import sys

from config.settings import get_settings
from src.utils.logger import configure_logging, get_logger


async def main() -> int:
    """メイン処理"""
    configure_logging()
    logger = get_logger(__name__)

    settings = get_settings()
    logger.info(
        "TikTok 自動投稿システム起動",
        dry_run=settings.dry_run,
        skip_tiktok_post=settings.skip_tiktok_post,
        target_categories=settings.category_list,
    )

    # Phase 7 で Orchestrator.run() を呼ぶ
    logger.warning("Phase 0: パイプライン未実装。スタブを実行中")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
