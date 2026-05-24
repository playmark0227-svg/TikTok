"""商品データモデル"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

ProductSource = Literal["amazon", "rakuten"]


@dataclass
class Product:
    """選定対象商品"""

    source: ProductSource
    product_id: str  # ASIN or itemCode
    title: str
    description: str
    price: int
    image_urls: list[str]
    review_count: int
    rating: float
    category: str
    affiliate_url: str
    score: float = 0.0
    ranking: int | None = None
    is_new: bool = False
    selected_at: datetime = field(default_factory=datetime.now)
    raw_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Firestore 保存用に dict 変換"""
        return {
            "source": self.source,
            "product_id": self.product_id,
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "image_urls": self.image_urls,
            "review_count": self.review_count,
            "rating": self.rating,
            "category": self.category,
            "affiliate_url": self.affiliate_url,
            "score": self.score,
            "ranking": self.ranking,
            "is_new": self.is_new,
            "selected_at": self.selected_at,
        }

    @property
    def display_title(self) -> str:
        """表示用に長すぎるタイトルを切り詰める"""
        if len(self.title) > 80:
            return self.title[:77] + "..."
        return self.title
