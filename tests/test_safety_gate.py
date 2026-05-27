"""セーフティゲートの単体テスト"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.orchestrator.safety_gate import check_safety
from src.prompt_generator.models import ContentPlan


def make_strong_plan() -> ContentPlan:
    return ContentPlan(
        veo_prompt_clip1="a", veo_prompt_clip2="b",
        caption="コレ知らない人マジで損してる🚨 在庫切れ続出中。コメ欄にリンク貼っとくね",
        hashtags=["#PR", "#広告", "#TikTok購入品", "#知らないと損",
                  "#バズり中", "#時短", "#一人暮らし", "#新生活"],
        subtitle_text="マジで神\n在庫切れ\nコメ欄リンク",
    )


@pytest.mark.unit
class TestSafetyGate:
    def test_strong_plan_passes(self):
        plan = make_strong_plan()
        result = check_safety(plan, total_slides=5)
        assert result.passed
        assert not result.blockers

    def test_missing_pr_tag_blocks(self):
        plan = make_strong_plan()
        plan.hashtags = [t for t in plan.hashtags if t.lower() != "#pr"]
        result = check_safety(plan)
        assert not result.passed
        assert any("#PR" in b for b in result.blockers)

    def test_legal_ng_blocks(self):
        plan = make_strong_plan()
        plan.caption = "絶対に痩せる商品です。100%効果あり。"
        result = check_safety(plan)
        assert not result.passed
        assert any("法的NG" in b for b in result.blockers)

    def test_placeholder_over_ratio_blocks(self):
        plan = make_strong_plan()
        result = check_safety(plan, used_placeholders=4, total_slides=5)
        assert not result.passed
        assert any("placeholder比率" in b for b in result.blockers)

    def test_placeholder_partial_warns_only(self):
        plan = make_strong_plan()
        result = check_safety(plan, used_placeholders=1, total_slides=5)
        assert result.passed
        assert any("placeholder" in w for w in result.warnings)

    def test_missing_video_blocks(self):
        plan = make_strong_plan()
        result = check_safety(plan, video_path=Path("/nonexistent.mp4"))
        assert not result.passed
        assert any("不在" in b for b in result.blockers)

    def test_empty_subtitle_blocks(self):
        plan = make_strong_plan()
        plan.subtitle_text = ""
        result = check_safety(plan)
        assert not result.passed
        assert any("字幕" in b for b in result.blockers)

    def test_too_long_caption_blocks(self):
        plan = make_strong_plan()
        plan.caption = "x" * 3000
        result = check_safety(plan)
        assert not result.passed
        assert any("上限超過" in b for b in result.blockers)
