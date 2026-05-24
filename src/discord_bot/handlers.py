"""Discord ハンドラユーティリティ

Bot とパイプライン間の橋渡しになるヘルパー関数群。
"""

from __future__ import annotations

from src.discord_bot.approval_flow import (
    ApprovalDecision,
    ApprovalQueue,
    ApprovalRequest,
)
from src.discord_bot.bot import ApprovalBot
from src.product_selector.models import Product
from src.prompt_generator.models import ContentPlan
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def request_approval(
    bot: ApprovalBot,
    product: Product,
    plan: ContentPlan,
    video_url: str,
    *,
    video_local_path: str = "",
    revision_count: int = 0,
    timeout_seconds: int = 86400,
) -> ApprovalDecision:
    """承認依頼を作成 → Discord 送信 → 承認待ち"""
    queue = bot.queue
    request = ApprovalRequest(
        product=product,
        plan=plan,
        video_url=video_url,
        video_local_path=video_local_path,
        revision_count=revision_count,
    )

    await bot.send_approval_request(request)
    decision = await queue.submit(request, timeout_seconds=timeout_seconds)
    logger.info(
        "承認結果",
        request_id=request.request_id,
        decision=decision.decision,
        revision_count=revision_count,
    )
    return decision


async def auto_approve_for_dry_run(
    queue: ApprovalQueue,
    request_id: str,
    *,
    decision: str = "approved",
    feedback: str = "",
) -> None:
    """テスト/DRY_RUN 用: 自動的に承認結果を投げる"""
    await queue.resolve(
        request_id,
        ApprovalDecision(
            request_id=request_id,
            decision=decision,  # type: ignore[arg-type]
            feedback=feedback,
            approved_by="dry_run",
        ),
    )
