"""Gemini クライアントの単体テスト"""

from __future__ import annotations

import json

import pytest

from config.settings import Settings
from src.product_selector.models import Product
from src.prompt_generator.gemini_client import (
    GeminiAPIError,
    GeminiContentClient,
)
from src.prompt_generator.models import ContentPlan


def make_product() -> Product:
    return Product(
        source="rakuten",
        product_id="testitem",
        title="テスト商品",
        description="説明文",
        price=3000,
        image_urls=[],
        review_count=100,
        rating=4.5,
        category="家電",
        affiliate_url="https://example.com",
    )


@pytest.mark.unit
class TestGeminiContentClient:
    @pytest.mark.asyncio
    async def test_generate_dry_run(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = GeminiContentClient(settings)
        plan = await client.generate(make_product())
        assert isinstance(plan, ContentPlan)
        assert plan.veo_prompt_clip1
        assert "#PR" in plan.hashtags
        assert "#広告" in plan.hashtags

    @pytest.mark.asyncio
    async def test_revise_dry_run_increments(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = GeminiContentClient(settings)
        product = make_product()
        v1 = await client.generate(product)
        v2 = await client.revise(product, v1, "もっと明るく")
        assert v2.revision_count == 1
        assert "[修正版" in v2.caption

    def test_get_client_raises_without_key(self):
        settings = Settings(_env_file=None, dry_run=False, gemini_api_key="")
        client = GeminiContentClient(settings)
        with pytest.raises(GeminiAPIError):
            client._get_client()

    def test_parse_response_valid_json(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = GeminiContentClient(settings)
        response = json.dumps(
            {
                "veo_prompt_clip1": "prompt1",
                "veo_prompt_clip2": "prompt2",
                "caption": "テスト本文",
                "hashtags": ["#PR", "#広告", "#test"],
                "subtitle_text": "字幕",
                "bgm_mood": "calm",
                "voice_style": "calm friendly",
            },
            ensure_ascii=False,
        )
        plan = client._parse_response(response)
        assert plan.caption == "テスト本文"
        assert plan.bgm_mood == "calm"
