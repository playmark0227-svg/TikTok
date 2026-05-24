"""Firestore クライアント

posts / products / tokens / daily_stats コレクションの読み書きを担当。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from config.settings import Settings, get_settings
from src.database.models import (
    DailyStats,
    PostRecord,
    ProductRecord,
    TokenRecord,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLLECTION_PRODUCTS = "products"
COLLECTION_POSTS = "posts"
COLLECTION_TOKENS = "tokens"
COLLECTION_DAILY_STATS = "daily_stats"


class FirestoreError(Exception):
    """Firestore 操作エラー"""


class FirestoreClient:
    """Firestore 操作クライアント

    DRY_RUN モードではメモリ上の辞書をストアとして使う。
    """

    def __init__(self, settings: Settings | None = None, client: Any = None):
        self.settings = settings or get_settings()
        self._client = client
        self._dry_run_store: dict[str, dict[str, dict]] = {
            COLLECTION_PRODUCTS: {},
            COLLECTION_POSTS: {},
            COLLECTION_TOKENS: {},
            COLLECTION_DAILY_STATS: {},
        }

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if self.settings.is_dry_run:
            logger.info("DRY_RUN: Firestore クライアント初期化スキップ(メモリ store)")
            self._client = "dry_run_client"
            return self._client

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
        except ImportError as e:
            raise FirestoreError("firebase-admin がインストールされていません") from e

        if not firebase_admin._apps:
            cred_path = self.settings.firebase_credentials_full_path
            if not cred_path.exists():
                raise FirestoreError(
                    f"Firebase 認証情報が見つかりません: {cred_path}"
                )
            cred = credentials.Certificate(str(cred_path))
            firebase_admin.initialize_app(
                cred,
                {
                    "projectId": self.settings.firebase_project_id,
                    "storageBucket": self.settings.firebase_storage_bucket,
                },
            )
        self._client = firestore.client()
        return self._client

    # ----- 共通操作 -----

    async def _set(self, collection: str, doc_id: str, data: dict) -> None:
        if self.settings.is_dry_run:
            self._dry_run_store.setdefault(collection, {})[doc_id] = data
            return
        client = self._get_client()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: client.collection(collection).document(doc_id).set(data),
        )

    async def _get(self, collection: str, doc_id: str) -> dict | None:
        if self.settings.is_dry_run:
            return self._dry_run_store.get(collection, {}).get(doc_id)
        client = self._get_client()
        loop = asyncio.get_event_loop()
        doc = await loop.run_in_executor(
            None,
            lambda: client.collection(collection).document(doc_id).get(),
        )
        if not doc.exists:
            return None
        return doc.to_dict()

    async def _query(
        self,
        collection: str,
        *,
        where: list[tuple[str, str, Any]] | None = None,
        order_by: str | None = None,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        if self.settings.is_dry_run:
            results = list(self._dry_run_store.get(collection, {}).values())
            if where:
                for field, op, value in where:
                    results = [
                        r for r in results if self._matches_where(r.get(field), op, value)
                    ]
            if order_by:
                results.sort(
                    key=lambda r: r.get(order_by, datetime.min),
                    reverse=descending,
                )
            if limit:
                results = results[:limit]
            return results

        client = self._get_client()
        loop = asyncio.get_event_loop()

        def _run() -> list[dict]:
            query = client.collection(collection)
            if where:
                for field, op, value in where:
                    query = query.where(field, op, value)
            if order_by:
                from google.cloud.firestore import Query  # type: ignore[import-not-found]

                direction = Query.DESCENDING if descending else Query.ASCENDING
                query = query.order_by(order_by, direction=direction)
            if limit:
                query = query.limit(limit)
            return [doc.to_dict() for doc in query.stream()]

        return await loop.run_in_executor(None, _run)

    @staticmethod
    def _matches_where(field_value: Any, op: str, value: Any) -> bool:
        if op == "==":
            return field_value == value
        if op == ">=":
            return field_value is not None and field_value >= value
        if op == "<=":
            return field_value is not None and field_value <= value
        if op == ">":
            return field_value is not None and field_value > value
        if op == "<":
            return field_value is not None and field_value < value
        return False

    # ----- products -----

    async def save_product(self, record: ProductRecord) -> None:
        logger.info("Firestore: product 保存", product_id=record.product_id)
        await self._set(COLLECTION_PRODUCTS, record.product_id, record.to_firestore())

    async def get_recent_product_ids(self, days: int = 30) -> set[str]:
        cutoff = datetime.now() - timedelta(days=days)
        results = await self._query(
            COLLECTION_PRODUCTS,
            where=[("posted_at", ">=", cutoff)],
        )
        return {r.get("product_id") for r in results if r.get("product_id")}

    # ----- posts -----

    async def save_post(self, record: PostRecord) -> None:
        logger.info("Firestore: post 保存", post_id=record.post_id, status=record.status)
        await self._set(COLLECTION_POSTS, record.post_id, record.to_firestore())

    async def update_post_status(
        self,
        post_id: str,
        status: str,
        *,
        tiktok_video_id: str | None = None,
        error: str | None = None,
    ) -> None:
        existing = await self._get(COLLECTION_POSTS, post_id) or {}
        existing["status"] = status
        if tiktok_video_id:
            existing["tiktok_video_id"] = tiktok_video_id
        if error:
            existing["error"] = error
        if status == "posted":
            existing["posted_at"] = datetime.now()
        await self._set(COLLECTION_POSTS, post_id, existing)

    async def get_top_posts(self, *, days: int = 30, limit: int = 5) -> list[dict]:
        """過去 N 日で再生数上位の投稿(few-shot 用)"""
        cutoff = datetime.now() - timedelta(days=days)
        results = await self._query(
            COLLECTION_POSTS,
            where=[("posted_at", ">=", cutoff), ("status", "==", "posted")],
        )
        results.sort(
            key=lambda r: (r.get("analytics") or {}).get("views", 0),
            reverse=True,
        )
        return results[:limit]

    # ----- tokens -----

    async def save_token(self, record: TokenRecord) -> None:
        logger.info("Firestore: token 保存", service=record.service)
        await self._set(COLLECTION_TOKENS, record.service, record.to_firestore())

    async def get_token(self, service: str) -> TokenRecord | None:
        data = await self._get(COLLECTION_TOKENS, service)
        if not data:
            return None
        try:
            return TokenRecord(**data)
        except Exception as e:
            logger.warning("token パース失敗", service=service, error=str(e))
            return None

    # ----- daily_stats -----

    async def get_daily_stats(self, date: str) -> DailyStats:
        data = await self._get(COLLECTION_DAILY_STATS, date)
        if data:
            return DailyStats(**data)
        return DailyStats(date=date)

    async def increment_daily_posts(self, date: str) -> None:
        stats = await self.get_daily_stats(date)
        stats.posts_count += 1
        await self._set(COLLECTION_DAILY_STATS, date, stats.to_firestore())
