"""商品選定モジュールの単体テスト"""

from __future__ import annotations

import pytest

from config.settings import Settings
from src.product_selector.amazon_client import AmazonClient
from src.product_selector.models import Product
from src.product_selector.rakuten_client import RakutenClient
from src.product_selector.scorer import PriceFitConfig, ProductScorer, ScoringWeights
from src.product_selector.selector import NoProductsFoundError, ProductSelector


def make_product(
    *,
    product_id: str = "P001",
    source: str = "amazon",
    price: int = 3000,
    review_count: int = 100,
    rating: float = 4.5,
    ranking: int | None = None,
    is_new: bool = False,
) -> Product:
    return Product(
        source=source,  # type: ignore[arg-type]
        product_id=product_id,
        title=f"Test Product {product_id}",
        description="テスト商品",
        price=price,
        image_urls=["https://example.com/img.jpg"],
        review_count=review_count,
        rating=rating,
        category="家電",
        affiliate_url=f"https://example.com/{product_id}",
        ranking=ranking,
        is_new=is_new,
    )


# ----- Scorer Tests -----


@pytest.mark.unit
class TestScorer:
    def test_review_count_score_zero_for_no_reviews(self):
        scorer = ProductScorer()
        product = make_product(review_count=0)
        scorer.score(product)
        assert product.score >= 0.0

    def test_review_count_score_higher_for_more_reviews(self):
        scorer = ProductScorer()
        low = make_product(product_id="L", review_count=10)
        high = make_product(product_id="H", review_count=10000)
        scorer.score(low)
        scorer.score(high)
        assert high.score > low.score

    def test_rating_score_high_for_5_stars(self):
        scorer = ProductScorer()
        low = make_product(product_id="L", rating=2.0)
        high = make_product(product_id="H", rating=5.0)
        scorer.score(low)
        scorer.score(high)
        assert high.score > low.score

    def test_price_fit_perfect_in_range(self):
        config = PriceFitConfig(ideal_min=2000, ideal_max=10000)
        scorer = ProductScorer(price_fit=config)
        assert scorer._price_fit_score(5000) == 1.0
        assert scorer._price_fit_score(2000) == 1.0
        assert scorer._price_fit_score(10000) == 1.0

    def test_price_fit_low_outside_range(self):
        config = PriceFitConfig(ideal_min=2000, ideal_max=10000)
        scorer = ProductScorer(price_fit=config)
        assert scorer._price_fit_score(500) < 1.0
        assert scorer._price_fit_score(50000) < 1.0

    def test_novelty_bonus(self):
        scorer = ProductScorer()
        assert scorer._novelty_score(True) > scorer._novelty_score(False)

    def test_ranking_top_is_high(self):
        scorer = ProductScorer()
        assert scorer._ranking_score(1) > scorer._ranking_score(20)
        assert scorer._ranking_score(None) == 0.0
        assert scorer._ranking_score(31) == 0.0

    def test_score_all_sorts_desc(self):
        scorer = ProductScorer()
        products = [
            make_product(product_id="A", review_count=10, rating=3.0),
            make_product(product_id="B", review_count=5000, rating=4.8, ranking=1),
            make_product(product_id="C", review_count=100, rating=4.0),
        ]
        sorted_products = scorer.score_all(products)
        assert sorted_products[0].score >= sorted_products[1].score
        assert sorted_products[1].score >= sorted_products[2].score

    def test_weights_normalize(self):
        w = ScoringWeights(
            review_count=2.0, rating=2.0, price_fit=2.0, novelty=2.0, ranking=2.0
        )
        normalized = w.normalize()
        total = (
            normalized.review_count
            + normalized.rating
            + normalized.price_fit
            + normalized.novelty
            + normalized.ranking
        )
        assert abs(total - 1.0) < 1e-9


# ----- Amazon Client (DRY_RUN) Tests -----


@pytest.mark.unit
class TestAmazonClient:
    @pytest.mark.asyncio
    async def test_search_items_dry_run_returns_products(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = AmazonClient(settings)
        products = await client.search_items("家電", item_count=3)
        assert len(products) > 0
        assert all(p.source == "amazon" for p in products)
        assert all(p.product_id.startswith("B0DRYRUN") for p in products)


# ----- Rakuten Client (DRY_RUN) Tests -----


@pytest.mark.unit
class TestRakutenClient:
    @pytest.mark.asyncio
    async def test_search_items_dry_run(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = RakutenClient(settings)
        products = await client.search_items("コスメ", hits=5)
        assert len(products) > 0
        assert all(p.source == "rakuten" for p in products)

    @pytest.mark.asyncio
    async def test_ranking_dry_run_sets_rank(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = RakutenClient(settings)
        products = await client.get_ranking(100026, hits=3)
        assert len(products) > 0
        assert all(p.ranking is not None for p in products)
        assert products[0].ranking == 1


# ----- Selector Tests -----


@pytest.mark.unit
class TestSelector:
    @pytest.mark.asyncio
    async def test_full_select_dry_run(self):
        settings = Settings(
            _env_file=None,
            dry_run=True,
            target_categories="家電,コスメ",
        )
        selector = ProductSelector(settings)
        product = await selector.select()
        assert product is not None
        assert product.score > 0
        assert product.product_id

    def test_deduplicate_removes_same_id(self):
        settings = Settings(_env_file=None, dry_run=True)
        selector = ProductSelector(settings)
        products = [
            make_product(product_id="X"),
            make_product(product_id="X"),
            make_product(product_id="Y"),
        ]
        deduped = selector.deduplicate(products)
        assert len(deduped) == 2

    def test_filter_by_history(self):
        settings = Settings(_env_file=None, dry_run=True)
        selector = ProductSelector(settings)
        products = [
            make_product(product_id="A"),
            make_product(product_id="B"),
            make_product(product_id="C"),
        ]
        filtered = selector.filter_by_history(products, {"B"})
        assert len(filtered) == 2
        assert all(p.product_id != "B" for p in filtered)

    def test_select_top_raises_for_empty(self):
        settings = Settings(_env_file=None, dry_run=True)
        selector = ProductSelector(settings)
        with pytest.raises(NoProductsFoundError):
            selector.select_top([])

    def test_select_top_returns_highest_when_not_random(self):
        settings = Settings(_env_file=None, dry_run=True)
        selector = ProductSelector(settings)
        products = [
            make_product(product_id="A", review_count=10),
            make_product(product_id="B", review_count=5000, rating=4.9, ranking=1),
        ]
        selected = selector.select_top(products, random_pick=False)
        assert selected.product_id == "B"


# ----- Product Model Tests -----


@pytest.mark.unit
class TestProductModel:
    def test_display_title_truncates_long_titles(self):
        p = make_product()
        p.title = "x" * 200
        assert len(p.display_title) <= 80

    def test_to_dict_contains_all_fields(self):
        p = make_product()
        d = p.to_dict()
        assert d["product_id"] == "P001"
        assert d["source"] == "amazon"
        assert "selected_at" in d
