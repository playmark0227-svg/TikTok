"""Discord 承認フロー

パイプラインから動画+企画を受信し、Discord に投稿して
ViFight のリアクション/返信を待機する。

非同期キューを介してパイプラインプロセスと Bot プロセスが通信する。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from src.product_selector.models import Product
from src.prompt_generator.models import ContentPlan
from src.utils.logger import get_logger

logger = get_logger(__name__)

DecisionType = Literal["approved", "revision", "rejected", "timeout"]

EMOJI_APPROVE = "✅"
EMOJI_REVISION = "✏️"
EMOJI_REJECT = "❌"


@dataclass
class ApprovalRequest:
    """承認依頼"""

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    product: Product | None = None
    plan: ContentPlan | None = None
    video_url: str = ""
    video_local_path: str = ""
    score_breakdown: dict = field(default_factory=dict)
    selection_reason: str = ""
    revision_count: int = 0


@dataclass
class ApprovalDecision:
    """承認結果"""

    request_id: str
    decision: DecisionType
    feedback: str = ""
    approved_by: str = ""
    decided_at: datetime = field(default_factory=datetime.now)

    @property
    def approved(self) -> bool:
        return self.decision == "approved"

    @property
    def rejected(self) -> bool:
        return self.decision == "rejected"

    @property
    def needs_revision(self) -> bool:
        return self.decision == "revision"


class ApprovalQueue:
    """承認待ち管理(プロセス間共有可能なシングルトンを想定)

    Phase 5: in-process Future ベース。
    将来的に Redis 等に差し替え可能。
    """

    _instance: ApprovalQueue | None = None

    def __init__(self):
        self._pending: dict[str, asyncio.Future[ApprovalDecision]] = {}
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> ApprovalQueue:
        if cls._instance is None:
            cls._instance = ApprovalQueue()
        return cls._instance

    async def submit(
        self,
        request: ApprovalRequest,
        *,
        timeout_seconds: int = 86400,
    ) -> ApprovalDecision:
        """承認待ちに登録、結果を待機"""
        async with self._lock:
            self._requests[request.request_id] = request
            future: asyncio.Future[ApprovalDecision] = asyncio.get_event_loop().create_future()
            self._pending[request.request_id] = future

        logger.info("承認待ちに登録", request_id=request.request_id)
        try:
            decision = await asyncio.wait_for(future, timeout=timeout_seconds)
            return decision
        except TimeoutError:
            logger.warning("承認タイムアウト", request_id=request.request_id)
            return ApprovalDecision(
                request_id=request.request_id,
                decision="timeout",
                feedback="24時間以内に承認されなかったため自動却下",
            )
        finally:
            async with self._lock:
                self._pending.pop(request.request_id, None)
                self._requests.pop(request.request_id, None)

    async def resolve(self, request_id: str, decision: ApprovalDecision) -> bool:
        """承認結果を通知"""
        async with self._lock:
            future = self._pending.get(request_id)
            if future is None or future.done():
                logger.warning("解決対象の承認依頼なし", request_id=request_id)
                return False
            future.set_result(decision)
            return True

    async def get_request(self, request_id: str) -> ApprovalRequest | None:
        async with self._lock:
            return self._requests.get(request_id)

    async def list_pending(self) -> list[ApprovalRequest]:
        async with self._lock:
            return list(self._requests.values())
