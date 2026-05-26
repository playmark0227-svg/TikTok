"""アプリケーション設定

.env から環境変数を読み込み、pydantic-settings で型安全に扱う。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """アプリケーション全体の設定"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- Claude API -----
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-4-7"

    # ----- Gemini / Veo -----
    gemini_api_key: str = ""
    veo_model: str = "veo-3.1-fast-generate-preview"

    # ----- Firebase -----
    firebase_project_id: str = ""
    firebase_credentials_path: str = "./firebase-credentials.json"
    firebase_storage_bucket: str = ""
    firestore_database_id: str = "(default)"

    # ----- Amazon PA-API -----
    amazon_access_key: str = ""
    amazon_secret_key: str = ""
    amazon_partner_tag: str = ""
    amazon_host: str = "webservices.amazon.co.jp"
    amazon_region: str = "us-west-2"

    # ----- 楽天 -----
    rakuten_app_id: str = ""
    rakuten_affiliate_id: str = ""

    # ----- TikTok -----
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = "http://localhost:8080/callback"
    tiktok_access_token: str = ""
    tiktok_refresh_token: str = ""
    tiktok_open_id: str = ""

    # ----- Discord -----
    discord_bot_token: str = ""
    discord_guild_id: str = ""
    discord_approval_channel_id: str = ""
    discord_notification_channel_id: str = ""
    discord_owner_user_id: str = ""

    # ----- 運用 -----
    timezone: str = "Asia/Tokyo"
    daily_post_time: str = "17:00"
    max_revision_count: int = 3
    video_duration_seconds: int = 16
    target_categories: str = "家電,コスメ,キッチン,健康,ガジェット"
    price_min: int = 1000
    price_max: int = 20000

    # ----- 動画生成モード -----
    # content_generator: "claude" | "gemini"
    content_generator: str = "claude"
    # video_mode: "veo" | "slideshow"  (slideshow: Gemini で静止画生成 → FFmpeg で連結)
    video_mode: str = "veo"
    # スライド枚数(slideshow モード時)
    slideshow_slide_count: int = 4
    slideshow_slide_duration: float = 2.5
    slideshow_transition_duration: float = 0.5
    exclude_recent_days: int = 30

    # ----- 開発フラグ -----
    dry_run: bool = True
    skip_tiktok_post: bool = True
    debug: bool = True
    log_level: str = "INFO"

    @field_validator("target_categories")
    @classmethod
    def _strip_categories(cls, v: str) -> str:
        return v.strip()

    @property
    def category_list(self) -> list[str]:
        """カンマ区切りのカテゴリを list に変換"""
        return [c.strip() for c in self.target_categories.split(",") if c.strip()]

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def storage_local_dir(self) -> Path:
        return PROJECT_ROOT / "storage_local"

    @property
    def assets_dir(self) -> Path:
        return PROJECT_ROOT / "assets"

    @property
    def firebase_credentials_full_path(self) -> Path:
        path = Path(self.firebase_credentials_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def is_dry_run(self) -> bool:
        return self.dry_run

    def validate_required(self, keys: list[str]) -> list[str]:
        """指定されたキーのうち、空のものを返す(起動時チェック用)"""
        missing: list[str] = []
        for key in keys:
            value = getattr(self, key, None)
            if not value:
                missing.append(key)
        return missing


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """シングルトン Settings を取得"""
    return Settings()
