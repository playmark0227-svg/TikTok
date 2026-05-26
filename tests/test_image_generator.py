"""Gemini 画像生成器の単体テスト"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import Settings
from src.video_generator.image_generator import (
    IMAGE_MODELS_FALLBACK,
    GeminiImageGenerator,
    ImageGenerationError,
)


@pytest.mark.unit
class TestGeminiImageGenerator:
    def test_get_client_raises_without_key(self):
        settings = Settings(_env_file=None, gemini_api_key="")
        gen = GeminiImageGenerator(settings)
        with pytest.raises(ImageGenerationError):
            gen._get_client()

    def test_fallback_models_list_non_empty(self):
        assert len(IMAGE_MODELS_FALLBACK) >= 2
        # 最も安価なモデルが先頭
        assert IMAGE_MODELS_FALLBACK[0] == "gemini-2.5-flash-image"

    def test_generate_raises_with_dummy_client_on_all_failures(self, tmp_path: Path):
        """ダミークライアントですべて失敗するケース"""

        class FailingClient:
            class _Models:
                def generate_content(self, **kwargs):
                    raise Exception("404 NOT_FOUND test")

                def generate_images(self, **kwargs):
                    raise Exception("404 NOT_FOUND test")

            models = _Models()

        settings = Settings(_env_file=None, gemini_api_key="test")
        gen = GeminiImageGenerator(settings, client=FailingClient())
        with pytest.raises(ImageGenerationError):
            gen.generate("test prompt", tmp_path / "out.png")
