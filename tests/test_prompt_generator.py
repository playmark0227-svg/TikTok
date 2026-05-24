"""企画生成モジュールの単体テスト"""

from __future__ import annotations

import json

import pytest

from config.settings import Settings
from src.product_selector.models import Product
from src.prompt_generator.claude_client import (
    ClaudeContentClient,
    PromptParseError,
)
from src.prompt_generator.models import ContentPlan
from src.prompt_generator.templates import (
    build_few_shot_block,
    build_prompt,
    build_revision_prompt,
)


def make_product() -> Product:
    return Product(
        source="amazon",
        product_id="B0XXXXX",
        title="超軽量 ワイヤレスイヤホン",
        description="高音質・長時間バッテリーで日々のリスニングを快適に。",
        price=4980,
        image_urls=["https://example.com/img.jpg"],
        review_count=1234,
        rating=4.5,
        category="ガジェット",
        affiliate_url="https://amazon.co.jp/dp/B0XXXXX",
    )


# ----- Template Tests -----


@pytest.mark.unit
class TestTemplates:
    def test_build_prompt_contains_product_info(self):
        product = make_product()
        prompt = build_prompt(product)
        assert product.title in prompt
        assert product.category in prompt
        assert "4,980" in prompt

    def test_build_prompt_includes_few_shot_when_provided(self):
        product = make_product()
        examples = [
            {
                "product_title": "サンプル商品",
                "caption": "サンプルキャプション",
                "hashtags": ["#PR", "#広告"],
                "veo_prompt_clip1": "Sample English prompt",
            }
        ]
        prompt = build_prompt(product, examples)
        assert "過去の好成績例" in prompt
        assert "サンプル商品" in prompt

    def test_build_few_shot_block_empty(self):
        assert build_few_shot_block([]) == ""

    def test_build_revision_prompt_includes_feedback(self):
        product = make_product()
        previous = '{"caption": "old"}'
        feedback = "もっと明るい雰囲気で"
        prompt = build_revision_prompt(product, previous, feedback)
        assert feedback in prompt
        assert previous in prompt


# ----- ContentPlan Tests -----


@pytest.mark.unit
class TestContentPlanModel:
    def test_full_caption_combines_parts(self):
        plan = ContentPlan(
            veo_prompt_clip1="a",
            veo_prompt_clip2="b",
            caption="本文",
            hashtags=["#PR", "#広告"],
            subtitle_text="字幕",
        )
        full = plan.full_caption
        assert "本文" in full
        assert "#PR" in full
        assert "プロフィール" in full

    def test_to_dict_contains_fields(self):
        plan = ContentPlan(
            veo_prompt_clip1="a",
            veo_prompt_clip2="b",
            caption="cap",
            hashtags=["#PR", "#広告"],
            subtitle_text="sub",
        )
        d = plan.to_dict()
        assert d["caption"] == "cap"
        assert d["bgm_mood"] == "upbeat"


# ----- Claude Client Tests -----


@pytest.mark.unit
class TestClaudeContentClient:
    @pytest.mark.asyncio
    async def test_generate_dry_run(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = ClaudeContentClient(settings)
        product = make_product()
        plan = await client.generate(product)
        assert plan.veo_prompt_clip1
        assert plan.veo_prompt_clip2
        assert plan.caption
        assert "#PR" in plan.hashtags
        assert "#広告" in plan.hashtags
        assert plan.bgm_mood in ("upbeat", "calm", "trendy")

    @pytest.mark.asyncio
    async def test_revise_dry_run_increments_revision(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = ClaudeContentClient(settings)
        product = make_product()
        plan_v1 = await client.generate(product)
        plan_v2 = await client.revise(product, plan_v1, "もっと明るく")
        assert plan_v2.revision_count == 1
        assert "[修正版" in plan_v2.caption

    def test_extract_json_from_code_fence(self):
        text = '```json\n{"caption": "test"}\n```'
        extracted = ClaudeContentClient._extract_json(text)
        assert json.loads(extracted) == {"caption": "test"}

    def test_extract_json_from_raw_json(self):
        text = '{"caption": "test"}'
        extracted = ClaudeContentClient._extract_json(text)
        assert json.loads(extracted) == {"caption": "test"}

    def test_extract_json_from_mixed_text(self):
        text = 'ここに前置きがあります {"caption": "test"} 余計な後ろ'
        extracted = ClaudeContentClient._extract_json(text)
        assert json.loads(extracted) == {"caption": "test"}

    def test_ensure_pr_tags_adds_missing(self):
        tags = ["#おすすめ", "#便利"]
        result = ClaudeContentClient._ensure_pr_tags(tags)
        assert "#PR" in result
        assert "#広告" in result

    def test_ensure_pr_tags_keeps_existing(self):
        tags = ["#PR", "#広告", "#test"]
        result = ClaudeContentClient._ensure_pr_tags(tags)
        assert result.count("#PR") == 1

    def test_ensure_pr_tags_adds_hash_prefix(self):
        tags = ["おすすめ", "便利"]
        result = ClaudeContentClient._ensure_pr_tags(tags)
        assert "#おすすめ" in result
        assert "#便利" in result

    def test_parse_response_valid_json(self):
        settings = Settings(_env_file=None, dry_run=False)
        # client は使わないので skipper を渡す
        client = ClaudeContentClient(settings, client="dummy")
        response = json.dumps(
            {
                "veo_prompt_clip1": "clip1 prompt",
                "veo_prompt_clip2": "clip2 prompt",
                "caption": "本文キャプション",
                "hashtags": ["#PR", "#広告", "#test"],
                "subtitle_text": "字幕\nテキスト",
                "bgm_mood": "calm",
                "voice_style": "calm friendly",
            },
            ensure_ascii=False,
        )
        plan = client._parse_response(response)
        assert plan.caption == "本文キャプション"
        assert plan.bgm_mood == "calm"
        assert "#PR" in plan.hashtags

    def test_parse_response_invalid_bgm_defaults_to_upbeat(self):
        settings = Settings(_env_file=None, dry_run=False)
        client = ClaudeContentClient(settings, client="dummy")
        response = json.dumps(
            {
                "veo_prompt_clip1": "a",
                "veo_prompt_clip2": "b",
                "caption": "c",
                "hashtags": ["#PR", "#広告"],
                "subtitle_text": "s",
                "bgm_mood": "invalid_mood",
            }
        )
        plan = client._parse_response(response)
        assert plan.bgm_mood == "upbeat"

    def test_parse_response_missing_field_raises(self):
        settings = Settings(_env_file=None, dry_run=False)
        client = ClaudeContentClient(settings, client="dummy")
        response = json.dumps({"caption": "incomplete"})
        with pytest.raises(PromptParseError):
            client._parse_response(response)

    def test_parse_response_invalid_json_raises(self):
        settings = Settings(_env_file=None, dry_run=False)
        client = ClaudeContentClient(settings, client="dummy")
        with pytest.raises(PromptParseError):
            client._parse_response("これは JSON ではない")
