"""動画生成モジュールの単体テスト"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import Settings
from src.prompt_generator.models import ContentPlan
from src.video_generator.veo_client import VeoClient


def make_plan() -> ContentPlan:
    return ContentPlan(
        veo_prompt_clip1="A clean studio shot of a product, vertical 9:16, 8 seconds",
        veo_prompt_clip2="A person using the product in soft natural light, 9:16, 8 seconds",
        caption="テスト",
        hashtags=["#PR", "#広告"],
        subtitle_text="テスト字幕",
    )


@pytest.mark.unit
class TestVeoClient:
    @pytest.mark.asyncio
    async def test_generate_video_dry_run_creates_file(self, tmp_path: Path):
        settings = Settings(_env_file=None, dry_run=True)
        client = VeoClient(settings)
        output = tmp_path / "test.mp4"
        result = await client.generate_video("test prompt", output, duration_seconds=4)
        assert result == output
        assert output.exists()

    @pytest.mark.asyncio
    async def test_generate_clips_for_plan_creates_two_files(self, tmp_path: Path):
        settings = Settings(_env_file=None, dry_run=True)
        client = VeoClient(settings)
        plan = make_plan()
        clips = await client.generate_clips_for_plan(plan, tmp_path)
        assert len(clips) == 2
        for clip in clips:
            assert clip.exists()
            assert clip.suffix == ".mp4"
