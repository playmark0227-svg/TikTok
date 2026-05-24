"""商品スコアリング

複数指標を重み付き合成して 0.0〜1.0 のスコアを算出する。
重みは config/categories.yaml で調整可能。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.product_selector.models import Product
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ScoringWeights:
    """スコアリング重み"""

    review_count: float = 0.30
    rating: float = 0.20
    price_fit: float = 0.10
    novelty: float = 0.15
    ranking: float = 0.25

    def normalize(self) -> ScoringWeights:
        """合計が 1.0 になるよう正規化"""
        total = self.review_count + self.rating + self.price_fit + self.novelty + self.ranking
        if total == 0:
            return self
        return ScoringWeights(
            review_count=self.review_count / total,
            rating=self.rating / total,
            price_fit=self.price_fit / total,
            novelty=self.novelty / total,
            ranking=self.ranking / total,
        )


@dataclass
class PriceFitConfig:
    """価格帯フィット設定"""

    ideal_min: int = 2000
    ideal_max: int = 10000


class ProductScorer:
    """商品スコアリングエンジン"""

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        price_fit: PriceFitConfig | None = None,
    ):
        self.weights = (weights or ScoringWeights()).normalize()
        self.price_fit = price_fit or PriceFitConfig()

    @classmethod
    def from_yaml(cls, path: Path | str) -> ProductScorer:
        """YAML 設定から構築"""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        weights_dict = data.get("scoring_weights", {})
        price_fit_dict = data.get("price_fit", {})
        return cls(
            weights=ScoringWeights(**weights_dict),
            price_fit=PriceFitConfig(**price_fit_dict),
        )

    def score(self, product: Product) -> float:
        """単一商品のスコアを算出"""
        rc = self._review_count_score(product.review_count)
        rt = self._rating_score(product.rating)
        pf = self._price_fit_score(product.price)
        nv = self._novelty_score(product.is_new)
        rk = self._ranking_score(product.ranking)

        composite = (
            rc * self.weights.review_count
            + rt * self.weights.rating
            + pf * self.weights.price_fit
            + nv * self.weights.novelty
            + rk * self.weights.ranking
        )
        composite = max(0.0, min(1.0, composite))
        product.score = composite

        logger.debug(
            "商品スコアリング",
            product_id=product.product_id,
            rc=round(rc, 3),
            rt=round(rt, 3),
            pf=round(pf, 3),
            nv=round(nv, 3),
            rk=round(rk, 3),
            composite=round(composite, 3),
        )
        return composite

    def score_all(self, products: list[Product]) -> list[Product]:
        """全商品をスコアリングしてスコア降順で返す"""
        for product in products:
            self.score(product)
        return sorted(products, key=lambda p: p.score, reverse=True)

    @staticmethod
    def _review_count_score(count: int) -> float:
        """レビュー数スコア(対数スケール、1000件で 1.0)"""
        if count <= 0:
            return 0.0
        return min(1.0, math.log10(count + 1) / 3.0)

    @staticmethod
    def _rating_score(rating: float) -> float:
        """評価スコア(4.0 以上で加点、5.0 で 1.0)"""
        if rating <= 0:
            return 0.0
        if rating < 3.0:
            return 0.1
        if rating < 4.0:
            return 0.4
        # 4.0 -> 0.6, 5.0 -> 1.0
        return min(1.0, 0.6 + (rating - 4.0) * 0.4)

    def _price_fit_score(self, price: int) -> float:
        """価格帯フィット(理想帯内で 1.0、外れるほど低下)"""
        if price <= 0:
            return 0.0
        if self.price_fit.ideal_min <= price <= self.price_fit.ideal_max:
            return 1.0
        if price < self.price_fit.ideal_min:
            ratio = price / self.price_fit.ideal_min
            return max(0.2, ratio)
        # price > ideal_max
        over = (price - self.price_fit.ideal_max) / self.price_fit.ideal_max
        return max(0.1, 1.0 - over * 0.5)

    @staticmethod
    def _novelty_score(is_new: bool) -> float:
        """新商品ボーナス"""
        return 1.0 if is_new else 0.3

    @staticmethod
    def _ranking_score(ranking: int | None) -> float:
        """ランキングスコア(1位で 1.0、30位で 0.0)"""
        if ranking is None or ranking <= 0:
            return 0.0
        if ranking > 30:
            return 0.0
        return max(0.0, 1.0 - (ranking - 1) / 30.0)
