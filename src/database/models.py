"""Firestore データモデル

Pydantic でバリデーション付きのデータクラスとして定義する。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProductRecord(BaseModel):
    """products コレクション"""

    product_id: str
    source: str  # "amazon" or "rakuten"
    title: str
    selected_at: datetime
    score: float = 0.0
    posted_at: datetime | None = None
    category: str = ""

    def to_firestore(self) -> dict[str, Any]:
        return self.model_dump()


class AnalyticsSnapshot(BaseModel):
    """投稿の分析データ"""

    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    updated_at: datetime | None = None


class PostRecord(BaseModel):
    """posts コレクション"""

    post_id: str
    product_id: str
    veo_prompt: str
    caption: str
    hashtags: list[str]
    video_url_storage: str = ""
    video_url_tiktok: str = ""
    tiktok_video_id: str = ""
    posted_at: datetime | None = None
    approved_by: str = ""
    revision_count: int = 0
    analytics: AnalyticsSnapshot = Field(default_factory=AnalyticsSnapshot)
    status: str = "draft"  # draft | approved | posted | rejected | failed
    error: str = ""

    def to_firestore(self) -> dict[str, Any]:
        return self.model_dump()


class TokenRecord(BaseModel):
    """tokens コレクション"""

    service: str  # "tiktok"
    access_token: str
    refresh_token: str
    expires_at: datetime
    updated_at: datetime

    def to_firestore(self) -> dict[str, Any]:
        return self.model_dump()


class DailyStats(BaseModel):
    """daily_stats コレクション"""

    date: str  # YYYY-MM-DD
    posts_count: int = 0
    total_views: int = 0
    total_engagement: int = 0

    def to_firestore(self) -> dict[str, Any]:
        return self.model_dump()
