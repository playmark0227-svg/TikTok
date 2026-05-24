"""パイプラインの試走スクリプト

DRY_RUN モードで全フロー(承認は自動承認)を回す。
本番起動前の動作確認用。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os  # noqa: E402

os.environ["DRY_RUN"] = "true"
os.environ["SKIP_TIKTOK_POST"] = "true"

from src.discord_bot.approval_flow import (  # noqa: E402
    ApprovalDecision,
    ApprovalQueue,
)
from src.orchestrator.pipeline import Pipeline  # noqa: E402
from src.utils.logger import configure_logging, get_logger  # noqa: E402


async def auto_approver(queue: ApprovalQueue) -> None:
    """承認待ちを自動承認するワーカ"""
    while True:
        await asyncio.sleep(0.5)
        pending = await queue.list_pending()
        for req in pending:
            await queue.resolve(
                req.request_id,
                ApprovalDecision(
                    request_id=req.request_id,
                    decision="approved",
                    approved_by="auto_test",
                ),
            )


async def main() -> int:
    configure_logging()
    logger = get_logger(__name__)
    logger.info("=== 試走開始 (DRY_RUN + 自動承認) ===")

    pipeline = Pipeline()
    approver_task = asyncio.create_task(auto_approver(pipeline.approval_queue))
    try:
        result = await pipeline.run()
    finally:
        approver_task.cancel()

    print("\n=== 試走結果 ===")
    print(f"成功         : {result.success}")
    print(f"post_id      : {result.post_id}")
    print(f"product_id   : {result.product_id}")
    print(f"tiktok_url   : {result.tiktok_url}")
    if result.error:
        print(f"error        : {result.error}")
    if result.skipped_reason:
        print(f"skipped      : {result.skipped_reason}")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
