"""楽天市場 API クライアント

公式 SDK は無いため httpx で直接呼び出す。
- IchibaItem/Search/20220601 — 商品検索
- IchibaItem/Ranking/20170628 — ジャンル別ランキング
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from src.product_selector.models import Product
from src.utils.logger import get_logger

logger = get_logger(__name__)

SEARCH_URL = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"
RANKING_URL = "https://app.rakuten.co.jp/services/api/IchibaItem/Ranking/20170628"
REQUEST_TIMEOUT = 15.0


class RakutenAPIError(Exception):
    """楽天 API エラー"""


class RakutenClient:
    """楽天市場 API クライアント"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._rate_limiter = asyncio.Semaphore(1)
        self._last_request_at = 0.0

    async def _throttle(self) -> None:
        """1 req/sec のレート制限"""
        async with self._rate_limiter:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request_at
            if elapsed < 1.0:
                await asyncio.sleep(1.0 - elapsed)
            self._last_request_at = asyncio.get_event_loop().time()

    def _validate_credentials(self) -> None:
        if not self.settings.rakuten_app_id:
            raise RakutenAPIError(
                "楽天 App ID が設定されていません (.env の RAKUTEN_APP_ID を確認)"
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((RakutenAPIError, httpx.HTTPError)),
        reraise=True,
    )
    async def search_items(
        self,
        keyword: str,
        *,
        genre_id: int | None = None,
        hits: int = 10,
        min_price: int | None = None,
        max_price: int | None = None,
        sort: str = "-reviewCount",
    ) -> list[Product]:
        """商品検索

        Args:
            keyword: 検索キーワード
            genre_id: ジャンルID
            hits: 取得件数 (1-30)
            min_price: 最低価格
            max_price: 最高価格
            sort: ソート順 (デフォルト: レビュー数降順)

        Returns:
            Product のリスト
        """
        logger.info("楽天 商品検索", keyword=keyword, genre_id=genre_id, hits=hits)

        if self.settings.is_dry_run:
            return self._dry_run_search(keyword, hits)

        self._validate_credentials()
        await self._throttle()

        params: dict[str, Any] = {
            "applicationId": self.settings.rakuten_app_id,
            "format": "json",
            "keyword": keyword,
            "hits": min(hits, 30),
            "sort": sort,
        }
        if self.settings.rakuten_affiliate_id:
            params["affiliateId"] = self.settings.rakuten_affiliate_id
        if genre_id:
            params["genreId"] = genre_id
        if min_price:
            params["minPrice"] = min_price
        if max_price:
            params["maxPrice"] = max_price

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(SEARCH_URL, params=params)
                response.raise_for_status()
                data = response.json()

            products = self._parse_search_response(data, keyword)
            logger.info("楽天 検索完了", count=len(products))
            return products
        except httpx.HTTPStatusError as e:
            logger.error("楽天 API HTTPエラー", status=e.response.status_code, body=e.response.text)
            raise RakutenAPIError(f"楽天 API エラー: {e.response.status_code}") from e
        except Exception as e:
            logger.error("楽天 検索エラー", error=str(e))
            raise RakutenAPIError(f"楽天検索失敗: {e}") from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((RakutenAPIError, httpx.HTTPError)),
        reraise=True,
    )
    async def get_ranking(self, genre_id: int, *, hits: int = 10) -> list[Product]:
        """ジャンル別ランキング取得"""
        logger.info("楽天 ランキング取得", genre_id=genre_id)

        if self.settings.is_dry_run:
            return self._dry_run_ranking(genre_id, hits)

        self._validate_credentials()
        await self._throttle()

        params: dict[str, Any] = {
            "applicationId": self.settings.rakuten_app_id,
            "format": "json",
            "genreId": genre_id,
        }
        if self.settings.rakuten_affiliate_id:
            params["affiliateId"] = self.settings.rakuten_affiliate_id

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(RANKING_URL, params=params)
                response.raise_for_status()
                data = response.json()

            products = self._parse_ranking_response(data, genre_id, hits)
            logger.info("楽天 ランキング取得完了", count=len(products))
            return products
        except httpx.HTTPStatusError as e:
            logger.error("楽天 ランキングHTTPエラー", status=e.response.status_code)
            raise RakutenAPIError(f"楽天ランキング失敗: {e.response.status_code}") from e
        except Exception as e:
            logger.error("楽天 ランキングエラー", error=str(e))
            raise RakutenAPIError(f"楽天ランキング失敗: {e}") from e

    def _parse_search_response(self, data: dict, category: str) -> list[Product]:
        items_wrapper = data.get("Items", [])
        products: list[Product] = []
        for entry in items_wrapper:
            item = entry.get("Item", entry)
            product = self._item_to_product(item, category)
            if product:
                products.append(product)
        return products

    def _parse_ranking_response(self, data: dict, genre_id: int, limit: int) -> list[Product]:
        items_wrapper = data.get("Items", [])
        products: list[Product] = []
        category = f"ranking_genre_{genre_id}"
        for entry in items_wrapper[:limit]:
            item = entry.get("Item", entry)
            product = self._item_to_product(item, category)
            if product:
                rank = item.get("rank") or item.get("Rank")
                if rank:
                    try:
                        product.ranking = int(rank)
                    except (ValueError, TypeError):
                        pass
                products.append(product)
        return products

    def _item_to_product(self, item: dict, category: str) -> Product | None:
        """楽天 Item を Product に変換"""
        item_code = item.get("itemCode")
        item_name = item.get("itemName")
        if not item_code or not item_name:
            return None

        price = int(item.get("itemPrice", 0) or 0)
        if price == 0:
            return None

        image_urls: list[str] = []
        for img in item.get("mediumImageUrls", []) or []:
            url = img.get("imageUrl") if isinstance(img, dict) else img
            if url:
                # 楽天はサムネイル URL に ?_ex=128x128 が付くため除去
                clean_url = url.split("?")[0]
                image_urls.append(clean_url)

        review_count = int(item.get("reviewCount", 0) or 0)
        rating = float(item.get("reviewAverage", 0) or 0)
        affiliate_url = item.get("affiliateUrl") or item.get("itemUrl") or ""
        description = item.get("itemCaption", "") or item_name

        return Product(
            source="rakuten",
            product_id=item_code,
            title=item_name,
            description=description[:500],
            price=price,
            image_urls=image_urls,
            review_count=review_count,
            rating=rating,
            category=category,
            affiliate_url=affiliate_url,
        )

    def _dry_run_search(self, keyword: str, hits: int) -> list[Product]:
        return [
            Product(
                source="rakuten",
                product_id=f"shop:itemcode-dry-{i}",
                title=f"[DRY-R] {keyword} の楽天サンプル {i}",
                description="DRY_RUN モードで生成された楽天テスト商品",
                price=1500 + i * 400,
                image_urls=[f"https://example.com/rakuten-{i}.jpg"],
                review_count=80 + i * 30,
                rating=3.8 + (i % 5) * 0.1,
                category=keyword,
                affiliate_url=f"https://hb.afl.rakuten.co.jp/dry-{i}",
            )
            for i in range(min(hits, 5))
        ]

    def _dry_run_ranking(self, genre_id: int, hits: int) -> list[Product]:
        products = self._dry_run_search(f"ranking-{genre_id}", hits)
        for i, p in enumerate(products):
            p.ranking = i + 1
            p.category = f"ranking_genre_{genre_id}"
        return products
