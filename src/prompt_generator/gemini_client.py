"""Google Gemini API クライアント (Claude の代替)

google-genai SDK で Gemini 2.5 Flash を呼んで ContentPlan を生成する。
無料 tier で 1500 リクエスト/日 まで使えるので、日次運用なら無料で回せる。
"""

from __future__ import annotations

from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from src.product_selector.models import Product
from src.prompt_generator.claude_client import ClaudeContentClient, PromptParseError
from src.prompt_generator.models import ContentPlan
from src.prompt_generator.templates import (
    SYSTEM_PROMPT,
    build_prompt,
    build_revision_prompt,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class GeminiAPIError(Exception):
    """Gemini API エラー"""


class GeminiContentClient:
    """Gemini ContentPlan 生成クライアント

    ClaudeContentClient と同じ ContentPlan インターフェース。
    パイプラインの prompt_client にそのまま差し込み可能。
    """

    def __init__(
        self,
        settings: Settings | None = None,
        client: Any = None,
        model: str | None = None,
    ):
        self.settings = settings or get_settings()
        self._client = client
        self.model = model or DEFAULT_GEMINI_MODEL

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if self.settings.is_dry_run:
            logger.info("DRY_RUN: Gemini クライアント初期化スキップ")
            self._client = "dry_run_client"
            return self._client

        try:
            from google import genai
        except ImportError as e:
            raise GeminiAPIError("google-genai SDK がインストールされていません") from e

        if not self.settings.gemini_api_key:
            raise GeminiAPIError("GEMINI_API_KEY が設定されていません (.env を確認)")

        self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(GeminiAPIError),
        reraise=True,
    )
    async def generate(
        self,
        product: Product,
        *,
        few_shot_examples: list[dict] | None = None,
    ) -> ContentPlan:
        """商品から ContentPlan を生成"""
        logger.info(
            "Gemini 企画生成開始",
            model=self.model,
            product_id=product.product_id,
            title=product.display_title,
        )

        if self.settings.is_dry_run:
            return self._dry_run_plan(product)

        user_prompt = build_prompt(product, few_shot_examples)
        response_text = self._call_gemini(user_prompt)
        plan = self._parse_response(response_text)
        logger.info(
            "Gemini 企画生成完了",
            product_id=product.product_id,
            caption_len=len(plan.caption),
            hashtag_count=len(plan.hashtags),
        )
        return plan

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(GeminiAPIError),
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
            "Gemini 企画修正",
            product_id=product.product_id,
            revision=previous_plan.revision_count + 1,
        )

        if self.settings.is_dry_run:
            plan = self._dry_run_plan(product)
            plan.revision_count = previous_plan.revision_count + 1
            plan.caption = f"[修正版 v{plan.revision_count}] {plan.caption}"
            return plan

        import json

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
        response_text = self._call_gemini(user_prompt)
        plan = self._parse_response(response_text)
        plan.revision_count = previous_plan.revision_count + 1
        return plan

    def _call_gemini(self, user_prompt: str) -> str:
        """Gemini を呼び出す"""
        client = self._get_client()
        try:
            from google.genai import types as genai_types

            response = client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.8,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
            )
            return response.text or ""
        except Exception as e:
            logger.error("Gemini API 呼び出しエラー", error=str(e))
            raise GeminiAPIError(f"Gemini API 呼び出し失敗: {e}") from e

    def _parse_response(self, response_text: str) -> ContentPlan:
        """Claude クライアントと同じパースロジックを再利用"""
        # 既存の Claude パーサーをそのまま使う
        try:
            # Claude の static method を借用(JSON 形式は同じ)
            return ClaudeContentClient._parse_response(
                ClaudeContentClient(self.settings, client="reuse"),
                response_text,
            )
        except PromptParseError:
            raise
        except Exception as e:
            raise PromptParseError(f"Gemini レスポンスパース失敗: {e}") from e

    def _dry_run_plan(self, product: Product) -> ContentPlan:
        """DRY_RUN 用ダミー(Claude と同じ)"""
        # Claude のダミーをそのまま使う
        claude_client = ClaudeContentClient(self.settings)
        return claude_client._dry_run_plan(product)
