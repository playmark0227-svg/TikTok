"""パイプライン統合テスト(DRY_RUN E2E)"""

from __future__ import annotations

import asyncio

import pytest

from config.settings import Settings
from src.discord_bot.approval_flow import ApprovalDecision, ApprovalQueue
from src.orchestrator.pipeline import Pipeline, PipelineResult


@pytest.fixture
def dry_run_settings():
    return Settings(
        _env_file=None,
        dry_run=True,
        skip_tiktok_post=True,
        target_categories="家電,コスメ",
        max_revision_count=2,
    )


async def auto_approve(queue: ApprovalQueue) -> None:
    while True:
        await asyncio.sleep(0.1)
        pending = await queue.list_pending()
        for req in pending:
            await queue.resolve(
                req.request_id,
                ApprovalDecision(
                    request_id=req.request_id,
                    decision="approved",
                    approved_by="test",
                ),
            )


async def auto_reject(queue: ApprovalQueue) -> None:
    while True:
        await asyncio.sleep(0.1)
        pending = await queue.list_pending()
        for req in pending:
            await queue.resolve(
                req.request_id,
                ApprovalDecision(
                    request_id=req.request_id,
                    decision="rejected",
                    feedback="test reject",
                    approved_by="test",
                ),
            )


async def auto_revise_then_approve(queue: ApprovalQueue) -> None:
    """1回 revision を返してから承認(各 request は別 ID なので回数で管理)"""
    handled = 0
    while True:
        await asyncio.sleep(0.1)
        pending = await queue.list_pending()
        for req in pending:
            handled += 1
            decision = "approved" if handled >= 2 else "revision"
            await queue.resolve(
                req.request_id,
                ApprovalDecision(
                    request_id=req.request_id,
                    decision=decision,  # type: ignore[arg-type]
                    feedback="もっと明るく" if decision == "revision" else "",
                    approved_by="test",
                ),
            )


@pytest.mark.unit
class TestPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_dry_run_success(self, dry_run_settings):
        queue = ApprovalQueue()
        pipeline = Pipeline(settings=dry_run_settings, approval_queue=queue)
        approver = asyncio.create_task(auto_approve(queue))
        try:
            result = await pipeline.run()
        finally:
            approver.cancel()
        assert isinstance(result, PipelineResult)
        assert result.success
        assert result.post_id
        assert result.product_id

    @pytest.mark.asyncio
    async def test_pipeline_rejection_stops(self, dry_run_settings):
        queue = ApprovalQueue()
        pipeline = Pipeline(settings=dry_run_settings, approval_queue=queue)
        rejector = asyncio.create_task(auto_reject(queue))
        try:
            result = await pipeline.run()
        finally:
            rejector.cancel()
        assert not result.success
        assert "rejected" in result.skipped_reason

    @pytest.mark.asyncio
    async def test_pipeline_revision_then_approve(self, dry_run_settings):
        queue = ApprovalQueue()
        pipeline = Pipeline(settings=dry_run_settings, approval_queue=queue)
        worker = asyncio.create_task(auto_revise_then_approve(queue))
        try:
            result = await pipeline.run()
        finally:
            worker.cancel()
        assert result.success
        assert result.post_id

    @pytest.mark.asyncio
    async def test_pipeline_creates_firestore_records(self, dry_run_settings):
        queue = ApprovalQueue()
        pipeline = Pipeline(settings=dry_run_settings, approval_queue=queue)
        approver = asyncio.create_task(auto_approve(queue))
        try:
            result = await pipeline.run()
        finally:
            approver.cancel()
        # Firestore に post 記録が残っているか
        if result.success:
            post = await pipeline.firestore._get("posts", result.post_id)
            assert post is not None
