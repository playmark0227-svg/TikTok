"""Claude API クライアント (Anthropic SDK)

商品情報から ContentPlan を生成する。
プロンプトキャッシュを有効化して、繰り返しのシステムプロンプトをキャッシュする。
"""

from __future__ import annotations

import json
import re
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from src.product_selector.models import Product
from src.prompt_generator.models import ContentPlan
from src.prompt_generator.templates import (
    SYSTEM_PROMPT,
    build_prompt,
    build_revision_prompt,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_TOKENS = 4096
TEMPERATURE = 0.8


class ClaudeAPIError(Exception):
    """Claude API エラー"""


class PromptParseError(Exception):
    """Claude のレスポンス JSON パース失敗"""


class ClaudeContentClient:
    """ContentPlan 生成クライアント"""

    def __init__(self, settings: Settings | None = None, client: Any = None):
        self.settings = settings or get_settings()
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if self.settings.is_dry_run:
            logger.info("DRY_RUN: Claude クライアント初期化スキップ")
            self._client = "dry_run_client"
            return self._client

        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ClaudeAPIError("anthropic SDK がインストールされていません") from e

        if not self.settings.anthropic_api_key:
            raise ClaudeAPIError(
                "ANTHROPIC_API_KEY が設定されていません (.env を確認)"
            )

        self._client = Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(ClaudeAPIError),
        reraise=True,
    )
    async def generate(
        self,
        product: Product,
        *,
        few_shot_examples: list[dict] | None = None,
    ) -> ContentPlan:
        """商品から ContentPlan を生成"""
        logger.info("企画生成開始", product_id=product.product_id, title=product.display_title)

        if self.settings.is_dry_run:
            return self._dry_run_plan(product)

        user_prompt = build_prompt(product, few_shot_examples)
        response_text = self._call_claude(user_prompt)
        plan = self._parse_response(response_text)
        logger.info(
            "企画生成完了",
            product_id=product.product_id,
            caption_len=len(plan.caption),
            hashtag_count=len(plan.hashtags),
        )
        return plan

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(ClaudeAPIError),
        reraise=True,
    )
    async def revise(
        self,
        product: Product,
        previous_plan: ContentPlan,
        feedback: str,
    ) -> ContentPlan:
        """フィードバックを反映して再生成"""
        logger.info(
            "企画修正",
            product_id=product.product_id,
            feedback_len=len(feedback),
            revision=previous_plan.revision_count + 1,
        )

        if self.settings.is_dry_run:
            plan = self._dry_run_plan(product)
            plan.revision_count = previous_plan.revision_count + 1
            plan.caption = f"[修正版 v{plan.revision_count}] {plan.caption}"
            return plan

        previous_json = json.dumps(
            {
                "veo_prompt_clip1": previous_plan.veo_prompt_clip1,
                "veo_prompt_clip2": previous_plan.veo_prompt_clip2,
                "caption": previous_plan.caption,
                "hashtags": previous_plan.hashtags,
                "subtitle_text": previous_plan.subtitle_text,
                "bgm_mood": previous_plan.bgm_mood,
            },
            ensure_ascii=False,
            indent=2,
        )
        user_prompt = build_revision_prompt(product, previous_json, feedback)
        response_text = self._call_claude(user_prompt)
        plan = self._parse_response(response_text)
        plan.revision_count = previous_plan.revision_count + 1
        return plan

    def _call_claude(self, user_prompt: str) -> str:
        """Claude を呼び出す(プロンプトキャッシュ有効)"""
        client = self._get_client()
        try:
            response = client.messages.create(
                model=self.settings.claude_model,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_prompt}],
            )
            text_parts = []
            for block in response.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
            return "".join(text_parts)
        except Exception as e:
            logger.error("Claude API 呼び出しエラー", error=str(e))
            raise ClaudeAPIError(f"Claude API 呼び出し失敗: {e}") from e

    def _parse_response(self, response_text: str) -> ContentPlan:
        """Claude のレスポンス文字列から ContentPlan を構築"""
        json_str = self._extract_json(response_text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error("JSON パース失敗", response=response_text[:500])
            raise PromptParseError(f"Claude レスポンスを JSON にパースできません: {e}") from e

        try:
            hashtags = data["hashtags"]
            if isinstance(hashtags, str):
                hashtags = [h.strip() for h in hashtags.split() if h.strip()]
            # #PR / #広告 を強制追加
            normalized_tags = self._ensure_pr_tags(hashtags)

            bgm = data.get("bgm_mood", "upbeat")
            if bgm not in ("upbeat", "calm", "trendy"):
                bgm = "upbeat"

            plan = ContentPlan(
                veo_prompt_clip1=data["veo_prompt_clip1"],
                veo_prompt_clip2=data["veo_prompt_clip2"],
                caption=data["caption"],
                hashtags=normalized_tags,
                subtitle_text=data["subtitle_text"],
                bgm_mood=bgm,  # type: ignore[arg-type]
                voice_style=data.get("voice_style", "energetic"),
                raw_response=response_text,
            )
            return plan
        except KeyError as e:
            raise PromptParseError(f"必須フィールドが不足: {e}") from e

    @staticmethod
    def _extract_json(text: str) -> str:
        """コードフェンスが混入していても JSON だけ取り出す"""
        text = text.strip()
        # ```json ... ``` 形式
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence_match:
            return fence_match.group(1)
        # 単に { ... } が含まれている場合
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            return brace_match.group(0)
        return text

    @staticmethod
    def _ensure_pr_tags(tags: list[str]) -> list[str]:
        """#PR と #広告 を必ず含める(ステマ規制対応)"""
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            t = tag.strip()
            if not t:
                continue
            if not t.startswith("#"):
                t = "#" + t
            lower = t.lower()
            if lower in seen:
                continue
            seen.add(lower)
            normalized.append(t)

        if "#pr" not in {t.lower() for t in normalized}:
            normalized.insert(0, "#PR")
        if "#広告" not in normalized:
            normalized.insert(1, "#広告")
        return normalized

    def _dry_run_plan(self, product: Product) -> ContentPlan:
        """DRY_RUN 用ダミー企画"""
        return ContentPlan(
            veo_prompt_clip1=(
                f"A vertical 9:16 video, 8 seconds. A modern {product.category} product "
                "is placed on a clean white studio surface. Soft cinematic lighting with "
                "subtle highlights. The camera slowly tracks in. Energetic background music."
            ),
            veo_prompt_clip2=(
                "A vertical 9:16 video, 8 seconds. A person in their 20s in a bright "
                "modern room demonstrates using the product. Soft natural light, warm tones. "
                "Quick cuts emphasize the result. Light upbeat music."
            ),
            caption=(
                f"これは便利✨ 話題の{product.category}アイテム、もう試した?\n"
                f"レビュー{product.review_count}件超え!プチプラで毎日が変わる💫"
            ),
            hashtags=[
                "#PR",
                "#広告",
                f"#{product.category}",
                "#おすすめ",
                "#便利グッズ",
                "#TikTok購入品",
                "#新生活",
                "#暮らしを整える",
            ],
            subtitle_text="知らないと損する\n話題のアイテム\nプロフリンクから",
            bgm_mood="upbeat",
            voice_style="energetic friendly",
            raw_response="[DRY_RUN] dummy plan",
        )
