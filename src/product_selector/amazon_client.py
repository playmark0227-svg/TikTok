"""Amazon PA-API 5.0 クライアント

python-amazon-paapi を使用して商品検索と人気商品取得を行う。
レート制限: 1 req/sec(売上比例で増加)
"""

from __future__ import annotations

import asyncio
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import Settings, get_settings
from src.product_selector.models import Product
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AmazonAPIError(Exception):
    """Amazon PA-API エラー"""


class AmazonClient:
    """Amazon PA-API クライアント"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client: Any = None
        self._rate_limiter = asyncio.Semaphore(1)
        self._last_request_at = 0.0

    def _get_client(self) -> Any:
        """遅延初期化"""
        if self._client is not None:
            return self._client

        if self.settings.is_dry_run:
            logger.info("DRY_RUN: Amazon クライアント初期化スキップ")
            self._client = "dry_run_client"
            return self._client

        try:
            from amazon_paapi import AmazonApi  # type: ignore[import-not-found]
        except ImportError as e:
            raise AmazonAPIError("python-amazon-paapi がインストールされていません") from e

        if not all(
            [
                self.settings.amazon_access_key,
                self.settings.amazon_secret_key,
                self.settings.amazon_partner_tag,
            ]
        ):
            raise AmazonAPIError(
                "Amazon 認証情報が不足しています (.env を確認: "
                "AMAZON_ACCESS_KEY / AMAZON_SECRET_KEY / AMAZON_PARTNER_TAG)"
            )

        self._client = AmazonApi(
            key=self.settings.amazon_access_key,
            secret=self.settings.amazon_secret_key,
            tag=self.settings.amazon_partner_tag,
            country="JP",
            throttling=1.0,
        )
        return self._client

    async def _throttle(self) -> None:
        """1 req/sec のレート制限を守る"""
        async with self._rate_limiter:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request_at
            if elapsed < 1.0:
                await asyncio.sleep(1.0 - elapsed)
            self._last_request_at = asyncio.get_event_loop().time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(AmazonAPIError),
        reraise=True,
    )
    async def search_items(
        self,
        keywords: str,
        *,
        browse_node_id: str | None = None,
        item_count: int = 10,
        min_price: int | None = None,
        max_price: int | None = None,
    ) -> list[Product]:
        """商品検索

        Args:
            keywords: 検索キーワード
            browse_node_id: カテゴリID
            item_count: 取得件数 (1-10)
            min_price: 最低価格(円)
            max_price: 最高価格(円)

        Returns:
            Product のリスト
        """
        logger.info(
            "Amazon 商品検索",
            keywords=keywords,
            browse_node_id=browse_node_id,
            item_count=item_count,
        )

        if self.settings.is_dry_run:
            return self._dry_run_search_items(keywords, item_count)

        await self._throttle()

        try:
            client = self._get_client()
            kwargs: dict[str, Any] = {
                "keywords": keywords,
                "item_count": min(item_count, 10),
            }
            if browse_node_id:
                kwargs["browse_node_id"] = browse_node_id
            if min_price:
                kwargs["min_price"] = min_price * 100  # PA-API は最小通貨単位
            if max_price:
                kwargs["max_price"] = max_price * 100

            result = client.search_items(**kwargs)
            products = self._parse_search_response(result, keywords)
            logger.info("Amazon 検索完了", count=len(products))
            return products
        except Exception as e:
            logger.error("Amazon 検索エラー", error=str(e))
            raise AmazonAPIError(f"Amazon 検索失敗: {e}") from e

    def _parse_search_response(self, result: Any, category: str) -> list[Product]:
        """PA-API レスポンスを Product にパース"""
        products: list[Product] = []
        items = getattr(result, "items", None) or []

        for item in items:
            try:
                product = self._item_to_product(item, category)
                if product:
                    products.append(product)
            except Exception as e:
                logger.warning("商品パース失敗", error=str(e))
                continue
        return products

    def _item_to_product(self, item: Any, category: str) -> Product | None:
        """単一の Item を Product に変換"""
        asin = getattr(item, "asin", None)
        if not asin:
            return None

        title = self._safe_get(item, "item_info", "title", "display_value", default="") or ""
        if not title:
            return None

        price_obj = self._safe_get(item, "offers", "listings")
        price = 0
        if price_obj and isinstance(price_obj, list) and len(price_obj) > 0:
            price_info = self._safe_get(price_obj[0], "price", "amount", default=0)
            price = int(price_info) if price_info else 0

        if price == 0:
            return None  # 価格不明はスキップ

        image_urls: list[str] = []
        primary = self._safe_get(item, "images", "primary", "large", "url")
        if primary:
            image_urls.append(primary)

        reviews_obj = getattr(item, "customer_reviews", None)
        review_count = 0
        rating = 0.0
        if reviews_obj:
            review_count = int(getattr(reviews_obj, "count", 0) or 0)
            rating = float(getattr(reviews_obj, "star_rating", 0) or 0)

        affiliate_url = getattr(item, "detail_page_url", "") or ""
        features = self._safe_get(item, "item_info", "features", "display_values", default=[])
        description = " / ".join(features) if features else title

        return Product(
            source="amazon",
            product_id=asin,
            title=title,
            description=description[:500],
            price=price,
            image_urls=image_urls,
            review_count=review_count,
            rating=rating,
            category=category,
            affiliate_url=affiliate_url,
        )

    @staticmethod
    def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
        """ネストした属性/辞書から安全に値を取得"""
        current = obj
        for key in keys:
            if current is None:
                return default
            if isinstance(current, dict):
                current = current.get(key)
            else:
                current = getattr(current, key, None)
        return current if current is not None else default

    def _dry_run_search_items(self, keywords: str, count: int) -> list[Product]:
        """DRY_RUN モードのダミーデータ"""
        return [
            Product(
                source="amazon",
                product_id=f"B0DRYRUN{i:03d}",
                title=f"[DRY] {keywords} のサンプル商品 {i}",
                description=f"DRY_RUN モードで生成された {keywords} のテスト商品",
                price=2000 + i * 500,
                image_urls=[f"https://example.com/dummy-{i}.jpg"],
                review_count=100 + i * 50,
                rating=4.0 + (i % 5) * 0.1,
                category=keywords,
                affiliate_url=f"https://amazon.co.jp/dp/B0DRYRUN{i:03d}",
            )
            for i in range(min(count, 5))
        ]
