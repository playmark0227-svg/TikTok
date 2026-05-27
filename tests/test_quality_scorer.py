"""コピー品質スコアラーの単体テスト"""

from __future__ import annotations

import pytest

from src.prompt_generator.models import ContentPlan
from src.prompt_generator.quality_scorer import (
    LEGAL_NG_PATTERNS,
    detect_legal_violations,
    score_caption,
    score_plan,
    score_subtitle,
)


@pytest.mark.unit
class TestLegalViolations:
    def test_detects_absolute_word(self):
        violations = detect_legal_violations("絶対に効きます")
        assert len(violations) > 0

    def test_detects_100_percent(self):
        violations = detect_legal_violations("100%効果あり")
        assert len(violations) > 0

    def test_detects_industry_no1(self):
        violations = detect_legal_violations("業界No.1の商品")
        assert len(violations) > 0

    def test_clean_text_no_violations(self):
        violations = detect_legal_violations("良い商品です。気になる方は試してください")
        assert violations == []


@pytest.mark.unit
class TestScoreCaption:
    def test_strong_copy_scores_high(self):
        caption = (
            "コレ知らない人マジで損してる🚨 レビュー1000件超えで在庫切れ続出中。"
            "私もうコレ無いと無理。コメ欄にリンク貼っとくね📌"
        )
        score = score_caption(caption)
        assert score.total > 0.5
        assert score.hook_strength > 0.3
        assert score.emotion_density > 0.3
        assert score.is_safe

    def test_weak_copy_scores_low(self):
        caption = "便利でおすすめです。ぜひお試しください。"
        score = score_caption(caption)
        assert score.total < 0.3
        assert score.weakness_penalty > 0

    def test_illegal_copy_marked_unsafe(self):
        caption = "絶対に痩せる商品です。100%効果あり。業界No.1。"
        score = score_caption(caption)
        assert not score.is_safe
        assert score.legal_safety < 1.0


@pytest.mark.unit
class TestScoreSubtitle:
    def test_short_punchy_subtitle_scores_high(self):
        sub = "コレ知ってる?🚨\nマジで人生変わる\n在庫切れ続出"
        score = score_subtitle(sub)
        assert score > 0.5

    def test_too_long_subtitle_scores_low(self):
        sub = "とても長い字幕で50文字を超えるような内容を書いてみた場合"
        score = score_subtitle(sub)
        assert score < 0.6

    def test_empty_subtitle_zero(self):
        assert score_subtitle("") == 0.0
        assert score_subtitle("\n\n") == 0.0


@pytest.mark.unit
class TestScorePlan:
    def test_full_plan_scoring(self):
        plan = ContentPlan(
            veo_prompt_clip1="a",
            veo_prompt_clip2="b",
            caption="コレ知らない人マジで損してる🚨 在庫切れ続出中。コメ欄にリンク",
            hashtags=["#PR", "#広告", "#test1", "#test2", "#test3", "#test4",
                      "#test5", "#test6", "#test7", "#test8"],
            subtitle_text="マジで神\n在庫切れ\nコメ欄リンク",
        )
        scores = score_plan(plan)
        assert "total" in scores
        assert scores["is_safe"] == 1.0
        assert scores["total"] > 0.3

    def test_plan_missing_pr_tag_fails(self):
        plan = ContentPlan(
            veo_prompt_clip1="a",
            veo_prompt_clip2="b",
            caption="テスト",
            hashtags=["#test"],
            subtitle_text="字幕",
        )
        scores = score_plan(plan)
        # ハッシュタグの規制違反は hashtag score = 0
        assert scores["hashtags"] == 0.0


@pytest.mark.unit
class TestPatternsLoaded:
    def test_legal_ng_patterns_non_empty(self):
        assert len(LEGAL_NG_PATTERNS) > 5
