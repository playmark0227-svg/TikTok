"""動画生成エンジン(Strategy パターン)のテスト"""

from __future__ import annotations

import pytest

from config.settings import Settings
from src.video_generator.engine import (
    SlideshowEngine,
    VeoEngine,
    build_engine,
)


@pytest.mark.unit
class TestBuildEngine:
    def test_veo_mode(self):
        settings = Settings(_env_file=None, dry_run=True, video_mode="veo")
        engine = build_engine(settings)
        assert isinstance(engine, VeoEngine)
        assert engine.name == "veo"

    def test_slideshow_mode(self):
        settings = Settings(_env_file=None, dry_run=True, video_mode="slideshow")
        engine = build_engine(settings)
        assert isinstance(engine, SlideshowEngine)
        assert engine.name == "slideshow"

    def test_unknown_mode_raises(self):
        settings = Settings(_env_file=None, dry_run=True, video_mode="invalid")
        with pytest.raises(ValueError):
            build_engine(settings)


@pytest.mark.unit
class TestEngineInterfaces:
    def test_veo_engine_has_generate(self):
        settings = Settings(_env_file=None, dry_run=True)
        engine = VeoEngine(settings)
        assert hasattr(engine, "generate")
        assert callable(engine.generate)

    def test_slideshow_engine_has_generate(self):
        settings = Settings(_env_file=None, dry_run=True)
        engine = SlideshowEngine(settings)
        assert hasattr(engine, "generate")
        assert callable(engine.generate)
