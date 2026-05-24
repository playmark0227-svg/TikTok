"""Firestore 初期化スクリプト

コレクションのインデックスを作成し、サンプルドキュメントを投入する。
初回セットアップ時に1度だけ実行する。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from src.database.firestore_client import (  # noqa: E402
    COLLECTION_DAILY_STATS,
    COLLECTION_POSTS,
    COLLECTION_PRODUCTS,
    COLLECTION_TOKENS,
    FirestoreClient,
    FirestoreError,
)
from src.database.models import DailyStats  # noqa: E402
from src.utils.logger import configure_logging, get_logger  # noqa: E402


async def main() -> int:
    configure_logging()
    logger = get_logger(__name__)
    settings = get_settings()

    if settings.is_dry_run:
        logger.warning(
            "DRY_RUN=true で起動中。実 Firestore への書き込みは行われません。"
            ".env で DRY_RUN=false に設定してください。"
        )

    missing = settings.validate_required(
        ["firebase_project_id", "firebase_storage_bucket"]
    )
    if missing and not settings.is_dry_run:
        logger.error("必須環境変数が未設定", missing=missing)
        return 1

    client = FirestoreClient(settings)
    try:
        # 接続確認のため軽くアクセス
        today = datetime.now().strftime("%Y-%m-%d")
        stats = await client.get_daily_stats(today)
        logger.info(
            "Firestore 接続確認 OK",
            today=today,
            posts_today=stats.posts_count,
        )

        # 初期データ投入(空の daily_stats)
        if stats.posts_count == 0:
            await client._set(
                COLLECTION_DAILY_STATS,
                today,
                DailyStats(date=today).to_firestore(),
            )
            logger.info("daily_stats 初期化完了")

        logger.info(
            "セットアップ完了",
            collections=[
                COLLECTION_PRODUCTS,
                COLLECTION_POSTS,
                COLLECTION_TOKENS,
                COLLECTION_DAILY_STATS,
            ],
        )
        print("\n✓ Firestore セットアップ完了")
        if settings.is_dry_run:
            print("  (DRY_RUN モードのため、メモリ store に書き込みました)")
        return 0
    except FirestoreError as e:
        logger.error("Firestore セットアップ失敗", error=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
