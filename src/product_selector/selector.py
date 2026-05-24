"""商品選定オーケストレーター

Amazon と楽天から候補を集めて、スコアリング → 重複除外 → ランダム選出。
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

import yaml

from config.settings import Settings, get_settings
from src.product_selector.amazon_client import AmazonClient
from src.product_selector.models import Product
from src.product_selector.rakuten_client import RakutenClient
from src.product_selector.scorer import ProductScorer
from src.utils.logger import get_logger

logger = get_logger(__name__)


class NoProductsFoundError(Exception):
    """候補商品が0件"""


class ProductSelector:
    """商品選定の司令塔"""

    def __init__(
        self,
        settings: Settings | None = None,
        amazon: AmazonClient | None = None,
        rakuten: RakutenClient | None = None,
        scorer: ProductScorer | None = None,
        categories_yaml_path: Path | str | None = None,
    ):
        self.settings = settings or get_settings()
        self.amazon = amazon or AmazonClient(self.settings)
        self.rakuten = rakuten or RakutenClient(self.settings)
        self.categories_yaml_path = (
            Path(categories_yaml_path)
            if categories_yaml_path
            else self.settings.project_root / "config" / "categories.yaml"
        )
        self.scorer = scorer or ProductScorer.from_yaml(self.categories_yaml_path)
        self._categories_cache: list[dict] | None = None

    def _load_categories(self) -> list[dict]:
        if self._categories_cache is not None:
            return self._categories_cache
        with open(self.categories_yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._categories_cache = data.get("categories", [])
        return self._categories_cache

    def _get_category_config(self, name: str) -> dict | None:
        for cat in self._load_categories():
            if cat["name"] == name:
                return cat
        return None

    async def collect_candidates(
        self,
        category_names: list[str] | None = None,
        *,
        per_category: int = 10,
    ) -> list[Product]:
        """各カテゴリから候補商品を集める"""
        names = category_names or self.settings.category_list
        logger.info("候補収集開始", categories=names, per_category=per_category)

        tasks = []
        for name in names:
            cat = self._get_category_config(name)
            if not cat:
                logger.warning("未定義カテゴリ", category=name)
                continue
            tasks.append(self._collect_for_category(cat, per_category))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_products: list[Product] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("カテゴリ収集エラー", error=str(result))
                continue
            all_products.extend(result)

        logger.info("候補収集完了", total=len(all_products))
        return all_products

    async def _collect_for_category(self, cat: dict, per_category: int) -> list[Product]:
        """単一カテゴリの収集(Amazon + 楽天)"""
        name = cat["name"]
        keywords = cat.get("keywords", [name])
        keyword = keywords[0] if keywords else name
        amazon_browse = cat.get("amazon_browse_node_id")
        rakuten_genre = cat.get("rakuten_genre_id")

        amazon_task = self.amazon.search_items(
            keywords=keyword,
            browse_node_id=amazon_browse,
            item_count=min(per_category, 10),
            min_price=self.settings.price_min,
            max_price=self.settings.price_max,
        )
        rakuten_search_task = self.rakuten.search_items(
            keyword=keyword,
            genre_id=rakuten_genre,
            hits=per_category,
            min_price=self.settings.price_min,
            max_price=self.settings.price_max,
        )

        tasks = [amazon_task, rakuten_search_task]
        if rakuten_genre:
            tasks.append(self.rakuten.get_ranking(rakuten_genre, hits=per_category))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        products: list[Product] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(
                    "API呼び出し失敗",
                    category=name,
                    error=str(result),
                )
                continue
            for p in result:
                p.category = name
                products.append(p)
        return products

    def filter_by_history(
        self,
        candidates: list[Product],
        recently_posted_ids: set[str],
    ) -> list[Product]:
        """過去 N 日に投稿済みの商品を除外"""
        before = len(candidates)
        filtered = [p for p in candidates if p.product_id not in recently_posted_ids]
        logger.info("履歴フィルタ", before=before, after=len(filtered))
        return filtered

    def deduplicate(self, products: list[Product]) -> list[Product]:
        """同一 product_id の重複を除外"""
        seen: set[str] = set()
        unique: list[Product] = []
        for p in products:
            key = f"{p.source}:{p.product_id}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)
        return unique

    def select_top(
        self,
        candidates: list[Product],
        *,
        top_n: int = 5,
        random_pick: bool = True,
    ) -> Product:
        """上位 N 件から1つ選出"""
        if not candidates:
            raise NoProductsFoundError("候補商品が0件です")

        scored = self.scorer.score_all(candidates)
        top = scored[:top_n]
        logger.info(
            "上位候補",
            count=len(top),
            scores=[round(p.score, 3) for p in top],
        )

        if random_pick and len(top) > 1:
            selected = random.choice(top)
        else:
            selected = top[0]

        logger.info(
            "商品選定",
            product_id=selected.product_id,
            source=selected.source,
            title=selected.display_title,
            score=round(selected.score, 3),
        )
        return selected

    async def select(
        self,
        *,
        recently_posted_ids: set[str] | None = None,
        category_names: list[str] | None = None,
    ) -> Product:
        """フルパイプライン: 収集 → 履歴除外 → 重複除外 → 選定"""
        candidates = await self.collect_candidates(category_names=category_names)
        candidates = self.deduplicate(candidates)
        if recently_posted_ids:
            candidates = self.filter_by_history(candidates, recently_posted_ids)
        return self.select_top(candidates)


async def _cli_main() -> None:
    """CLI 実行用エントリ"""
    from src.utils.logger import configure_logging

    configure_logging()
    selector = ProductSelector()
    try:
        product = await selector.select()
        print("\n=== 選定商品 ===")
        print(f"ソース    : {product.source}")
        print(f"ID        : {product.product_id}")
        print(f"タイトル  : {product.title}")
        print(f"価格      : ¥{product.price:,}")
        print(f"評価      : {product.rating} ({product.review_count}件)")
        print(f"スコア    : {round(product.score, 3)}")
        print(f"URL       : {product.affiliate_url}")
    except NoProductsFoundError as e:
        print(f"\n候補商品なし: {e}")


if __name__ == "__main__":
    asyncio.run(_cli_main())
