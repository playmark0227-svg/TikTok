"""本番モード即時実行

通常 launchd が毎日17:00 に main.py を呼ぶのと同じフローを、手動で1回実行する。

注意:
- Amazon/楽天 API キーが未取得のため、商品選定だけは事前定義のサンプルを使う
- それ以外(Gemini, FFmpeg, Firestore メモリ store, etc.) は全て本物
- SKIP_TIKTOK_POST=true なので TikTok 投稿はしないが、API リクエスト直前まで全フローが走る
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from src.database.firestore_client import FirestoreClient  # noqa: E402
from src.discord_bot.approval_flow import (  # noqa: E402
    ApprovalDecision,
    ApprovalQueue,
)
from src.orchestrator.pipeline import Pipeline  # noqa: E402
from src.product_selector.models import Product  # noqa: E402
from src.product_selector.selector import ProductSelector  # noqa: E402
from src.storage.firebase_client import FirebaseStorageClient  # noqa: E402
from src.utils.logger import configure_logging, get_logger  # noqa: E402


def make_realistic_product() -> Product:
    """Amazon/楽天 API 未設定のための代替品.
    現実的なデータ構造で本番と同じ Product を返す."""
    return Product(
        source="amazon",
        product_id="B0SAMPLEPROD1",
        title="衣類スチーマー ハンディアイロン コードレス 軽量 旅行 出張 ワイシャツ",
        description=(
            "コードレスで使える携帯型の衣類スチーマー。15秒で立ち上がり、"
            "アイロン台不要でハンガーにかけたまま使える。"
            "シワ伸ばしと除菌・消臭が同時にできる。"
        ),
        price=4980,
        image_urls=[],
        review_count=1342,
        rating=4.4,
        category="家電",
        affiliate_url="https://www.amazon.co.jp/dp/B0SAMPLEPROD1",
        score=0.85,
        selected_at=datetime.now(),
    )


class HardcodedSelector(ProductSelector):
    """商品選定の代わりに事前定義 product を返す(Amazon/楽天 キー未取得時)"""

    async def select(self, **kwargs):  # type: ignore[override]
        return make_realistic_product()


async def auto_approver(queue: ApprovalQueue) -> None:
    """承認待ちが来たら自動承認(Discord Bot 未設定のため)"""
    while True:
        await asyncio.sleep(0.5)
        pending = await queue.list_pending()
        for req in pending:
            await queue.resolve(
                req.request_id,
                ApprovalDecision(
                    request_id=req.request_id,
                    decision="approved",
                    approved_by="run_now_auto",
                ),
            )


async def main() -> int:
    configure_logging()
    logger = get_logger(__name__)
    settings = get_settings()

    logger.info(
        "=== 本番モード即時実行 ===",
        content_generator=settings.content_generator,
        video_mode=settings.video_mode,
        skip_tiktok=settings.skip_tiktok_post,
    )

    if settings.is_dry_run:
        logger.error("DRY_RUN=true では本番実行できない。.env を確認")
        return 1

    # Firebase / Discord / TikTok のキーは未設定なので、それらだけ dry_run override
    fs_settings = settings.model_copy(update={"dry_run": True})
    firestore = FirestoreClient(fs_settings)
    storage_client = FirebaseStorageClient(fs_settings)

    from src.discord_bot.bot import ApprovalBot

    queue = ApprovalQueue()
    bot = ApprovalBot(settings=fs_settings, queue=queue)
    selector = HardcodedSelector(settings)
    pipeline = Pipeline(
        settings=settings,
        selector=selector,
        approval_queue=queue,
        firestore=firestore,
        storage_client=storage_client,
        approval_bot=bot,
    )

    approver_task = asyncio.create_task(auto_approver(queue))
    try:
        result = await pipeline.run()
    finally:
        approver_task.cancel()

    print("\n" + "=" * 70)
    print(" 本番実行結果")
    print("=" * 70)
    print(f"  success      : {result.success}")
    print(f"  post_id      : {result.post_id}")
    print(f"  product_id   : {result.product_id}")
    print(f"  tiktok_url   : {result.tiktok_url}")
    if result.error:
        print(f"  error        : {result.error}")
    if result.skipped_reason:
        print(f"  skipped      : {result.skipped_reason}")

    # 最終動画のパスを探す
    edited = settings.storage_local_dir / "edited"
    if result.post_id:
        candidates = sorted(edited.glob(f"{result.post_id}_*_final.mp4"))
        if candidates:
            final = candidates[-1]
            size_mb = final.stat().st_size / 1024 / 1024
            print(f"\n📹 最終動画: {final}")
            print(f"   サイズ  : {size_mb:.2f} MB")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
