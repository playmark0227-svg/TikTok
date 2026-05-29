"""Google Gemini API クライアント (Claude の代替)

google-genai SDK で Gemini 2.5 Flash を呼んで ContentPlan を生成する。
無料 tier で 1500 リクエスト/日 まで使えるので、日次運用なら無料で回せる。
共通ロジックは BaseContentClient を参照。
"""

from __future__ import annotations

from typing import Any

from config.settings import Settings, get_settings
from src.prompt_generator.base_client import (
    MAX_TOKENS,
    TEMPERATURE,
    BaseContentClient,
    ContentGenerationError,
)
from src.prompt_generator.templates import SYSTEM_PROMPT
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

__all__ = ["GeminiContentClient", "GeminiAPIError"]


class GeminiAPIError(ContentGenerationError):
    """Gemini API エラー"""


class GeminiContentClient(BaseContentClient):
    """ContentPlan 生成クライアント (Gemini)

    BaseContentClient と同じインターフェイス。
    パイプラインの prompt_client にそのまま差し込み可能。
    """

    provider_name = "gemini"

    def __init__(
        self,
        settings: Settings | None = None,
        client: Any = None,
        model: str | None = None,
    ):
        super().__init__(settings or get_settings(), client)
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

    def _call_llm(self, user_prompt: str) -> str:
        """Gemini を呼び出す(JSON モード)"""
        client = self._get_client()
        try:
            from google.genai import types as genai_types

            response = client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=TEMPERATURE,
                    max_output_tokens=MAX_TOKENS,
                    response_mime_type="application/json",
                ),
            )
            return response.text or ""
        except Exception as e:
            logger.error("Gemini API 呼び出しエラー", error=str(e))
            raise GeminiAPIError(f"Gemini API 呼び出し失敗: {e}") from e
