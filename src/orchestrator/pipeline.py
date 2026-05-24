"""パイプラインオーケストレーター

商品選定 → 企画生成 → 動画生成 → 編集 → アップロード → Discord承認 → TikTok投稿
の全フローを統合する。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config.settings import Settings, get_settings
from src.database.firestore_client import FirestoreClient
from src.database.models import PostRecord, ProductRecord
from src.discord_bot.approval_flow import ApprovalDecision, ApprovalQueue
from src.discord_bot.bot import ApprovalBot
from src.discord_bot.handlers import request_approval
from src.product_selector.models import Product
from src.product_selector.selector import (
    NoProductsFoundError,
    ProductSelector,
)
from src.prompt_generator.claude_client import ClaudeContentClient
from src.prompt_generator.models import ContentPlan
from src.storage.firebase_client import FirebaseStorageClient
from src.storage.local_cache import LocalCache
from src.tiktok_publisher.publisher import TikTokPublisher
from src.utils.logger import get_logger
from src.utils.notifier import notify_error, notify_info
from src.video_editor.processor import VideoProcessor
from src.video_generator.veo_client import VeoClient

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    """パイプライン実行結果"""

    success: bool
    post_id: str = ""
    product_id: str = ""
    tiktok_url: str = ""
    error: str = ""
    skipped_reason: str = ""


class Pipeline:
    """全体オーケストレーター"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        selector: ProductSelector | None = None,
        prompt_client: ClaudeContentClient | None = None,
        veo_client: VeoClient | None = None,
        video_processor: VideoProcessor | None = None,
        storage_client: FirebaseStorageClient | None = None,
        firestore: FirestoreClient | None = None,
        publisher: TikTokPublisher | None = None,
        approval_bot: ApprovalBot | None = None,
        approval_queue: ApprovalQueue | None = None,
        local_cache: LocalCache | None = None,
    ):
        self.settings = settings or get_settings()
        self.firestore = firestore or FirestoreClient(self.settings)
        self.selector = selector or ProductSelector(self.settings)
        self.prompt_client = prompt_client or ClaudeContentClient(self.settings)
        self.veo_client = veo_client or VeoClient(self.settings)
        self.video_processor = video_processor or VideoProcessor(self.settings)
        self.storage = storage_client or FirebaseStorageClient(self.settings)
        self.publisher = publisher or TikTokPublisher(self.settings)
        self.approval_queue = approval_queue or ApprovalQueue.instance()
        self.approval_bot = approval_bot or ApprovalBot(
            settings=self.settings, queue=self.approval_queue
        )
        self.local_cache = local_cache or LocalCache(self.settings)

    async def run(self) -> PipelineResult:
        """日次パイプラインを実行"""
        post_id = f"post_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        logger.info("=== パイプライン開始 ===", post_id=post_id)

        try:
            # 0. ローカルキャッシュ整理
            self.local_cache.cleanup_old_files()

            # 1. 商品選定
            product = await self._select_product()
            if product is None:
                return PipelineResult(
                    success=False,
                    post_id=post_id,
                    skipped_reason="候補商品なし",
                )

            # 2. 企画生成
            few_shots = await self._fetch_few_shots()
            plan = await self.prompt_client.generate(product, few_shot_examples=few_shots)

            # 3-6. 動画生成→編集→アップロード→承認ループ
            final_video_url = ""
            final_video_path: Path | None = None
            decision: ApprovalDecision | None = None

            for revision in range(self.settings.max_revision_count + 1):
                logger.info("生成→承認サイクル", revision=revision, post_id=post_id)

                # 3. 動画生成
                generated_dir = self.settings.storage_local_dir / "generated"
                clip_paths = await self.veo_client.generate_clips_for_plan(
                    plan, generated_dir
                )

                # 4. 動画編集
                final_video_path = self.video_processor.process(
                    clip_paths,
                    plan,
                    output_dir=self.settings.storage_local_dir / "edited",
                    post_id=f"{post_id}_v{revision}",
                )

                # 5. アップロード
                upload_result = await self.storage.upload_video(
                    final_video_path,
                    remote_name=f"videos/{post_id}_v{revision}.mp4",
                )
                final_video_url = upload_result["signed_url"]

                # 6. Discord 承認待ち
                decision = await request_approval(
                    self.approval_bot,
                    product,
                    plan,
                    final_video_url,
                    video_local_path=str(final_video_path),
                    revision_count=revision,
                )

                if decision.approved:
                    break
                if decision.rejected or decision.decision == "timeout":
                    await self._save_rejection(
                        post_id, product, plan, decision, final_video_url
                    )
                    return PipelineResult(
                        success=False,
                        post_id=post_id,
                        product_id=product.product_id,
                        skipped_reason=f"承認結果: {decision.decision}",
                    )

                # revision の場合は修正
                logger.info("企画修正", feedback=decision.feedback[:80])
                plan = await self.prompt_client.revise(product, plan, decision.feedback)

            # 修正回数上限に達した場合
            if decision is None or not decision.approved:
                await self._save_rejection(
                    post_id, product, plan,
                    decision or ApprovalDecision(request_id="", decision="rejected"),
                    final_video_url,
                )
                return PipelineResult(
                    success=False,
                    post_id=post_id,
                    product_id=product.product_id,
                    skipped_reason="修正回数上限",
                )

            # 7. TikTok 投稿
            publish_result = await self.publisher.publish_from_url(
                final_video_url, plan, product
            )

            # 8. 記録
            await self._save_success(
                post_id, product, plan, final_video_url, publish_result, decision
            )

            # 9. 完了通知
            await self._notify_success(post_id, product, publish_result)

            logger.info("=== パイプライン完了 ===", post_id=post_id, tiktok=publish_result.tiktok_url)
            return PipelineResult(
                success=True,
                post_id=post_id,
                product_id=product.product_id,
                tiktok_url=publish_result.tiktok_url,
            )

        except NoProductsFoundError as e:
            logger.warning("候補商品なし", error=str(e))
            await notify_error(f"候補商品なし: {e}")
            return PipelineResult(
                success=False, post_id=post_id, skipped_reason=str(e)
            )
        except Exception as e:
            logger.exception("パイプライン失敗", post_id=post_id)
            await notify_error("パイプライン失敗", exc=e)
            return PipelineResult(success=False, post_id=post_id, error=str(e))

    async def _select_product(self) -> Product | None:
        try:
            recent_ids = await self.firestore.get_recent_product_ids(
                days=self.settings.exclude_recent_days
            )
            return await self.selector.select(recently_posted_ids=recent_ids)
        except NoProductsFoundError:
            return None

    async def _fetch_few_shots(self) -> list[dict]:
        """過去30日で好成績だった投稿を few-shot に使う"""
        try:
            top_posts = await self.firestore.get_top_posts(days=30, limit=5)
            return [
                {
                    "product_title": p.get("product_id", ""),
                    "caption": p.get("caption", ""),
                    "hashtags": p.get("hashtags", []),
                    "veo_prompt_clip1": p.get("veo_prompt", ""),
                }
                for p in top_posts
            ]
        except Exception as e:
            logger.warning("few-shot 取得失敗", error=str(e))
            return []

    async def _save_rejection(
        self,
        post_id: str,
        product: Product,
        plan: ContentPlan,
        decision: ApprovalDecision,
        video_url: str,
    ) -> None:
        record = PostRecord(
            post_id=post_id,
            product_id=product.product_id,
            veo_prompt=plan.veo_prompt_clip1,
            caption=plan.caption,
            hashtags=plan.hashtags,
            video_url_storage=video_url,
            approved_by=decision.approved_by,
            revision_count=plan.revision_count,
            status=decision.decision,
            error=decision.feedback,
        )
        await self.firestore.save_post(record)

    async def _save_success(
        self,
        post_id: str,
        product: Product,
        plan: ContentPlan,
        video_url: str,
        publish_result,
        decision: ApprovalDecision,
    ) -> None:
        product_record = ProductRecord(
            product_id=product.product_id,
            source=product.source,
            title=product.title,
            selected_at=product.selected_at,
            score=product.score,
            posted_at=datetime.now(),
            category=product.category,
        )
        await self.firestore.save_product(product_record)

        post_record = PostRecord(
            post_id=post_id,
            product_id=product.product_id,
            veo_prompt=plan.veo_prompt_clip1,
            caption=plan.caption,
            hashtags=plan.hashtags,
            video_url_storage=video_url,
            video_url_tiktok=publish_result.tiktok_url,
            tiktok_video_id=publish_result.tiktok_video_id,
            posted_at=publish_result.posted_at,
            approved_by=decision.approved_by,
            revision_count=plan.revision_count,
            status="posted" if not self.settings.skip_tiktok_post else "approved",
        )
        await self.firestore.save_post(post_record)

        today = datetime.now().strftime("%Y-%m-%d")
        await self.firestore.increment_daily_posts(today)

    async def _notify_success(self, post_id: str, product: Product, publish_result) -> None:
        message = (
            f"✅ 投稿完了: {product.display_title}\n"
            f"  post_id: {post_id}\n"
            f"  TikTok: {publish_result.tiktok_url}"
        )
        await self.approval_bot.send_notification(message)
        await notify_info(message)


async def run_pipeline_once() -> PipelineResult:
    """1回だけパイプラインを実行(launchd 日次起動用)"""
    pipeline = Pipeline()
    return await pipeline.run()


async def run_pipeline_with_bot() -> PipelineResult:
    """Bot を裏で起動しながらパイプラインを実行

    Bot プロセスが別途常駐していない場合のヘルパ。
    DRY_RUN モードでは Bot は無効。
    """
    pipeline = Pipeline()
    if not pipeline.settings.is_dry_run:
        bot_task = asyncio.create_task(pipeline.approval_bot.start())
        try:
            await pipeline.approval_bot.wait_until_ready(timeout=10)
        except TimeoutError:
            logger.warning("Bot 起動タイムアウト、続行")
        try:
            return await pipeline.run()
        finally:
            bot_task.cancel()
    else:
        return await pipeline.run()
