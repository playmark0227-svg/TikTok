"""Gemini 画像生成クライアント

Gemini 2.5 Flash Image (Nano Banana) または Imagen を使ってスライド画像を生成する。
無料 tier で使える可能性のある順にフォールバック:
1. gemini-2.5-flash-image (Nano Banana) - 安価・高速
2. imagen-4.0-fast-generate-001 - 高品質
3. imagen-3.0-fast-generate-001 - 旧版
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ImageGenerationError(Exception):
    """画像生成エラー"""


IMAGE_MODELS_FALLBACK = [
    "gemini-2.5-flash-image",
    "imagen-4.0-fast-generate-001",
    "imagen-3.0-generate-002",
]


class GeminiImageGenerator:
    """Gemini で画像を生成して PNG ファイルに保存"""

    def __init__(self, settings: Settings | None = None, client: Any = None):
        self.settings = settings or get_settings()
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as e:
            raise ImageGenerationError("google-genai SDK がインストールされていません") from e
        if not self.settings.gemini_api_key:
            raise ImageGenerationError("GEMINI_API_KEY が未設定")
        self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type(ImageGenerationError),
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        output: Path,
        *,
        aspect_ratio: str = "9:16",
    ) -> Path:
        """画像を1枚生成

        Args:
            prompt: 英語プロンプト推奨(モデルの強みが出る)
            output: 保存先 PNG パス
            aspect_ratio: "9:16" / "1:1" / "16:9"

        Returns:
            生成した PNG のパス
        """
        output.parent.mkdir(parents=True, exist_ok=True)
        client = self._get_client()

        last_error: Exception | None = None
        for model in IMAGE_MODELS_FALLBACK:
            try:
                logger.info("画像生成試行", model=model, prompt_preview=prompt[:80])
                if model.startswith("imagen"):
                    return self._generate_with_imagen(client, model, prompt, output, aspect_ratio)
                else:
                    return self._generate_with_gemini_image(
                        client, model, prompt, output, aspect_ratio
                    )
            except Exception as e:
                last_error = e
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    logger.warning(
                        "モデル使用不可(quota/billing)、次のモデルへフォールバック",
                        model=model,
                    )
                    continue
                if "404" in err_msg or "not found" in err_msg.lower():
                    logger.warning("モデル未提供、次へ", model=model)
                    continue
                logger.warning("画像生成失敗、次のモデルへ", model=model, error=err_msg[:200])
                continue

        raise ImageGenerationError(
            f"全モデルで生成失敗。最後のエラー: {last_error}"
        )

    def _generate_with_gemini_image(
        self,
        client: Any,
        model: str,
        prompt: str,
        output: Path,
        aspect_ratio: str,
    ) -> Path:
        """Nano Banana 等の Gemini 系画像生成"""
        from google.genai import types as genai_types

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        for candidate in response.candidates or []:
            for part in (candidate.content.parts or []):
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    data = inline.data
                    if isinstance(data, str):
                        data = base64.b64decode(data)
                    output.write_bytes(data)
                    logger.info("画像保存", path=str(output), size=len(data))
                    return output
        raise ImageGenerationError(f"{model}: 画像データがレスポンスに含まれない")

    def _generate_with_imagen(
        self,
        client: Any,
        model: str,
        prompt: str,
        output: Path,
        aspect_ratio: str,
    ) -> Path:
        """Imagen 系"""
        from google.genai import types as genai_types

        response = client.models.generate_images(
            model=model,
            prompt=prompt,
            config=genai_types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio=aspect_ratio,
            ),
        )

        for image in response.generated_images or []:
            image_bytes = image.image.image_bytes
            if image_bytes:
                output.write_bytes(image_bytes)
                logger.info("Imagen 保存", path=str(output), size=len(image_bytes))
                return output
        raise ImageGenerationError(f"{model}: Imagen レスポンスが空")
