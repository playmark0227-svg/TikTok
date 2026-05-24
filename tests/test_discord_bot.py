"""Discord Bot モジュールの単体テスト"""

from __future__ import annotations

import asyncio

import pytest

from config.settings import Settings
from src.discord_bot.approval_flow import (
    ApprovalDecision,
    ApprovalQueue,
    ApprovalRequest,
)
from src.discord_bot.bot import ApprovalBot
from src.discord_bot.handlers import auto_approve_for_dry_run, request_approval
from src.product_selector.models import Product
from src.prompt_generator.models import ContentPlan


def make_product() -> Product:
    return Product(
        source="amazon",
        product_id="P1",
        title="テスト商品",
        description="説明",
        price=3000,
        image_urls=["https://example.com/img.jpg"],
        review_count=100,
        rating=4.5,
        category="家電",
        affiliate_url="https://example.com",
        score=0.8,
    )


def make_plan() -> ContentPlan:
    return ContentPlan(
        veo_prompt_clip1="a",
        veo_prompt_clip2="b",
        caption="テストキャプション",
        hashtags=["#PR", "#広告"],
        subtitle_text="字幕",
    )


@pytest.mark.unit
class TestApprovalDecision:
    def test_approved_flag(self):
        d = ApprovalDecision(request_id="r", decision="approved")
        assert d.approved is True
        assert d.rejected is False
        assert d.needs_revision is False

    def test_rejected_flag(self):
        d = ApprovalDecision(request_id="r", decision="rejected")
        assert d.rejected is True

    def test_revision_flag(self):
        d = ApprovalDecision(request_id="r", decision="revision", feedback="more")
        assert d.needs_revision is True


@pytest.mark.unit
class TestApprovalQueue:
    @pytest.mark.asyncio
    async def test_submit_and_resolve(self):
        queue = ApprovalQueue()
        request = ApprovalRequest(product=make_product(), plan=make_plan())

        async def resolver():
            await asyncio.sleep(0.05)
            await queue.resolve(
                request.request_id,
                ApprovalDecision(request_id=request.request_id, decision="approved"),
            )

        asyncio.create_task(resolver())
        decision = await queue.submit(request, timeout_seconds=5)
        assert decision.approved

    @pytest.mark.asyncio
    async def test_submit_timeout(self):
        queue = ApprovalQueue()
        request = ApprovalRequest(product=make_product(), plan=make_plan())
        decision = await queue.submit(request, timeout_seconds=0.1)
        assert decision.decision == "timeout"

    @pytest.mark.asyncio
    async def test_resolve_unknown_returns_false(self):
        queue = ApprovalQueue()
        result = await queue.resolve(
            "nonexistent",
            ApprovalDecision(request_id="nonexistent", decision="approved"),
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_list_pending(self):
        queue = ApprovalQueue()
        request = ApprovalRequest(product=make_product(), plan=make_plan())

        async def resolver():
            await asyncio.sleep(0.1)
            pending = await queue.list_pending()
            assert len(pending) >= 1
            await queue.resolve(
                request.request_id,
                ApprovalDecision(request_id=request.request_id, decision="approved"),
            )

        asyncio.create_task(resolver())
        await queue.submit(request, timeout_seconds=5)

    def test_singleton_instance(self):
        a = ApprovalQueue.instance()
        b = ApprovalQueue.instance()
        assert a is b


@pytest.mark.unit
class TestApprovalBot:
    @pytest.mark.asyncio
    async def test_send_approval_request_dry_run(self):
        settings = Settings(_env_file=None, dry_run=True)
        queue = ApprovalQueue()
        bot = ApprovalBot(settings=settings, queue=queue)
        request = ApprovalRequest(product=make_product(), plan=make_plan())
        # DRY_RUN なので例外なしで完了する
        await bot.send_approval_request(request)

    @pytest.mark.asyncio
    async def test_start_dry_run_returns_immediately(self):
        settings = Settings(_env_file=None, dry_run=True)
        bot = ApprovalBot(settings=settings)
        await bot.start()  # 例外なしで return

    def test_build_content_includes_product_info(self):
        settings = Settings(_env_file=None, dry_run=True)
        bot = ApprovalBot(settings=settings)
        request = ApprovalRequest(product=make_product(), plan=make_plan())
        content = bot._build_content(request)
        assert "テスト商品" in content
        assert "#PR" in content
        assert "✅" in content


@pytest.mark.unit
class TestHandlers:
    @pytest.mark.asyncio
    async def test_request_approval_full_flow(self):
        settings = Settings(_env_file=None, dry_run=True)
        queue = ApprovalQueue()
        bot = ApprovalBot(settings=settings, queue=queue)

        async def approver():
            await asyncio.sleep(0.1)
            pending = await queue.list_pending()
            assert pending
            await auto_approve_for_dry_run(queue, pending[0].request_id)

        asyncio.create_task(approver())
        decision = await request_approval(
            bot,
            make_product(),
            make_plan(),
            "https://example.com/video.mp4",
            timeout_seconds=5,
        )
        assert decision.approved

    @pytest.mark.asyncio
    async def test_request_approval_revision_flow(self):
        settings = Settings(_env_file=None, dry_run=True)
        queue = ApprovalQueue()
        bot = ApprovalBot(settings=settings, queue=queue)

        async def reviewer():
            await asyncio.sleep(0.1)
            pending = await queue.list_pending()
            await auto_approve_for_dry_run(
                queue,
                pending[0].request_id,
                decision="revision",
                feedback="もっと明るく",
            )

        asyncio.create_task(reviewer())
        decision = await request_approval(
            bot,
            make_product(),
            make_plan(),
            "https://example.com/video.mp4",
            timeout_seconds=5,
        )
        assert decision.needs_revision
        assert decision.feedback == "もっと明るく"
