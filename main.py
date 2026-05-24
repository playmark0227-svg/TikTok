"""エントリポイント

毎日17:00に launchd から起動され、パイプラインを実行する。

使い方:
  python main.py             # パイプラインを1回実行
  python main.py --bot       # Discord Bot を常駐起動
  python main.py --dry-run   # DRY_RUN モード強制
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from config.settings import get_settings
from src.discord_bot.bot import ApprovalBot
from src.orchestrator.pipeline import run_pipeline_with_bot
from src.utils.logger import configure_logging, get_logger


async def run_pipeline() -> int:
    logger = get_logger(__name__)
    settings = get_settings()
    logger.info(
        "パイプライン起動",
        dry_run=settings.dry_run,
        skip_tiktok_post=settings.skip_tiktok_post,
        target_categories=settings.category_list,
    )
    result = await run_pipeline_with_bot()
    if result.success:
        logger.info("パイプライン成功", post_id=result.post_id, tiktok=result.tiktok_url)
        return 0
    logger.warning(
        "パイプライン未完了",
        post_id=result.post_id,
        skipped=result.skipped_reason,
        error=result.error,
    )
    return 1


async def run_bot() -> int:
    logger = get_logger(__name__)
    settings = get_settings()
    if settings.is_dry_run:
        logger.warning("DRY_RUN モードでは Bot は起動しません")
        return 0
    logger.info("Discord Bot 常駐起動")
    bot = ApprovalBot(settings=settings)
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Bot 停止")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="TikTok 自動投稿システム")
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Discord Bot を常駐起動(launchd の Bot 用)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DRY_RUN モードを強制",
    )
    args = parser.parse_args()

    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
        os.environ["SKIP_TIKTOK_POST"] = "true"

    configure_logging()

    if args.bot:
        return await run_bot()
    return await run_pipeline()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
