"""TikTok 投稿モジュールの単体テスト"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from config.settings import Settings
from src.database.firestore_client import FirestoreClient
from src.database.models import TokenRecord
from src.product_selector.models import Product
from src.prompt_generator.models import ContentPlan
from src.tiktok_publisher.oauth import (
    OAUTH_SCOPES,
    TikTokOAuthError,
    TikTokOAuthManager,
)
from src.tiktok_publisher.publisher import (
    MAX_CAPTION_LENGTH,
    PublishResult,
    TikTokPublisher,
    validate_caption,
)


def make_product() -> Product:
    return Product(
        source="amazon",
        product_id="P1",
        title="テスト商品",
        description="説明",
        price=3000,
        image_urls=["https://example.com/img.jpg"],
        review_count=100,
        rating=4.5,
        category="家電",
        affiliate_url="https://example.com",
    )


def make_plan() -> ContentPlan:
    return ContentPlan(
        veo_prompt_clip1="a",
        veo_prompt_clip2="b",
        caption="テストキャプション",
        hashtags=["#PR", "#広告", "#テスト"],
        subtitle_text="字幕",
    )


# ----- OAuth Tests -----


@pytest.mark.unit
class TestTikTokOAuthManager:
    def test_build_authorize_url_includes_scope(self):
        settings = Settings(
            _env_file=None,
            dry_run=True,
            tiktok_client_key="ck123",
            tiktok_redirect_uri="http://localhost:8080/callback",
        )
        oauth = TikTokOAuthManager(settings)
        url = oauth.build_authorize_url(state="abc")
        assert "ck123" in url
        assert "state=abc" in url
        for scope in OAUTH_SCOPES:
            assert scope in url

    @pytest.mark.asyncio
    async def test_exchange_code_dry_run(self):
        settings = Settings(_env_file=None, dry_run=True)
        oauth = TikTokOAuthManager(settings)
        token = await oauth.exchange_code("dummycode")
        assert token.access_token
        assert token.refresh_token
        assert token.expires_at > datetime.now()

    @pytest.mark.asyncio
    async def test_refresh_dry_run(self):
        settings = Settings(_env_file=None, dry_run=True)
        oauth = TikTokOAuthManager(settings)
        token = await oauth.refresh("dummy_refresh")
        assert token.access_token

    @pytest.mark.asyncio
    async def test_get_valid_token_dry_run(self):
        settings = Settings(_env_file=None, dry_run=True)
        oauth = TikTokOAuthManager(settings)
        token = await oauth.get_valid_access_token()
        assert token == "dry_run_access_token"

    @pytest.mark.asyncio
    async def test_get_valid_token_uses_env_fallback(self):
        settings = Settings(
            _env_file=None,
            dry_run=False,
            skip_tiktok_post=True,
            tiktok_access_token="env_token",
        )
        firestore = FirestoreClient(Settings(_env_file=None, dry_run=True))
        oauth = TikTokOAuthManager(settings=settings, firestore_client=firestore)
        token = await oauth.get_valid_access_token()
        assert token == "env_token"

    @pytest.mark.asyncio
    async def test_get_valid_token_no_token_raises(self):
        settings = Settings(_env_file=None, dry_run=False, tiktok_access_token="")
        firestore = FirestoreClient(Settings(_env_file=None, dry_run=True))
        oauth = TikTokOAuthManager(settings=settings, firestore_client=firestore)
        with pytest.raises(TikTokOAuthError):
            await oauth.get_valid_access_token()

    @pytest.mark.asyncio
    async def test_get_valid_token_refreshes_when_expiring(self):
        settings = Settings(_env_file=None, dry_run=True)
        firestore = FirestoreClient(settings)
        oauth = TikTokOAuthManager(settings=settings, firestore_client=firestore)
        # 期限切れ間近のトークンを保存
        expiring = TokenRecord(
            service="tiktok",
            access_token="old_token",
            refresh_token="rtoken",
            expires_at=datetime.now() + timedelta(minutes=10),
            updated_at=datetime.now(),
        )
        await firestore.save_token(expiring)
        token = await oauth.get_valid_access_token()
        # DRY_RUN なので refresh で dry_run_access_token を返す
        assert token == "dry_run_access_token"


# ----- Publisher Tests -----


@pytest.mark.unit
class TestTikTokPublisher:
    @pytest.mark.asyncio
    async def test_publish_dry_run(self):
        settings = Settings(_env_file=None, dry_run=True, skip_tiktok_post=False)
        publisher = TikTokPublisher(settings)
        result = await publisher.publish_from_url(
            "https://example.com/video.mp4",
            make_plan(),
            make_product(),
        )
        assert result.success
        assert "dry_run" in result.publish_id

    @pytest.mark.asyncio
    async def test_publish_skip_tiktok(self):
        settings = Settings(_env_file=None, dry_run=False, skip_tiktok_post=True)
        publisher = TikTokPublisher(settings)
        result = await publisher.publish_from_url(
            "https://example.com/video.mp4",
            make_plan(),
            make_product(),
        )
        assert result.success
        assert result.publish_id == "skipped"

    def test_build_caption_truncates_long_input(self):
        settings = Settings(_env_file=None, dry_run=True)
        publisher = TikTokPublisher(settings)
        plan = make_plan()
        plan.caption = "a" * (MAX_CAPTION_LENGTH + 500)
        caption = publisher.build_caption(plan, make_product())
        assert len(caption) <= MAX_CAPTION_LENGTH

    def test_pick_privacy_level_picks_public(self):
        result = TikTokPublisher._pick_privacy_level(
            {"privacy_level_options": ["SELF_ONLY", "PUBLIC_TO_EVERYONE"]}
        )
        assert result == "PUBLIC_TO_EVERYONE"

    def test_pick_privacy_level_default(self):
        result = TikTokPublisher._pick_privacy_level({})
        assert result == "PUBLIC_TO_EVERYONE"


@pytest.mark.unit
class TestValidateCaption:
    def test_valid_caption_passes(self):
        ok, warnings = validate_caption("良い商品です #PR #広告")
        assert ok
        assert warnings == []

    def test_missing_pr_warns(self):
        ok, warnings = validate_caption("良い商品です #広告")
        assert not ok
        assert any("#PR" in w for w in warnings)

    def test_missing_ad_warns(self):
        ok, warnings = validate_caption("良い商品です #PR")
        assert not ok
        assert any("#広告" in w for w in warnings)

    def test_hyperbole_warns(self):
        ok, warnings = validate_caption("絶対痩せる!業界No.1!#PR #広告")
        assert not ok
        assert any("誇大広告" in w for w in warnings)


@pytest.mark.unit
class TestPublishResult:
    def test_publish_result_dataclass(self):
        r = PublishResult(success=True, publish_id="P1")
        assert r.success
        assert r.publish_id == "P1"
