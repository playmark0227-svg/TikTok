"""Claude API クライアント (Anthropic SDK)

商品情報から ContentPlan を生成する。
プロンプトキャッシュを有効化して、繰り返しのシステムプロンプトをキャッシュする。
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
    PromptParseError,
)
from src.prompt_generator.templates import SYSTEM_PROMPT
from src.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "ClaudeContentClient",
    "ClaudeAPIError",
    "PromptParseError",
]


class ClaudeAPIError(ContentGenerationError):
    """Claude API エラー"""


class ClaudeContentClient(BaseContentClient):
    """ContentPlan 生成クライアント (Claude)"""

    provider_name = "claude"

    def __init__(self, settings: Settings | None = None, client: Any = None):
        super().__init__(settings or get_settings(), client)

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
            raise ClaudeAPIError("ANTHROPIC_API_KEY が設定されていません (.env を確認)")
        self._client = Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    def _call_llm(self, user_prompt: str) -> str:
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
            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            return "".join(text_parts)
        except Exception as e:
            logger.error("Claude API 呼び出しエラー", error=str(e))
            raise ClaudeAPIError(f"Claude API 呼び出し失敗: {e}") from e
