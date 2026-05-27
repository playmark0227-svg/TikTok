"""投稿前セーフティゲート

動画 + 企画を最終チェックし、本物の品質に達してなければ自動却下。
- 法的リスク(薬機法・景表法 NGワード)
- ステマ規制対応(#PR/#広告)
- 品質スコア(コピー・字幕)
- placeholder 検出(画像生成失敗時の自動却下)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.prompt_generator.models import ContentPlan
from src.prompt_generator.quality_scorer import (
    detect_legal_violations,
    score_plan,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SafetyResult:
    passed: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def block_reason(self) -> str:
        return " / ".join(self.blockers)


def check_safety(
    plan: ContentPlan,
    video_path: Path | None = None,
    *,
    used_placeholders: int = 0,
    total_slides: int = 0,
    min_quality_score: float = 0.4,
    allow_placeholder_ratio: float = 0.5,
) -> SafetyResult:
    """投稿可否を判定

    Args:
        plan: 企画
        video_path: 最終動画(存在チェック)
        used_placeholders: AI 画像生成失敗で placeholder にした枚数
        total_slides: 総スライド枚数
        min_quality_score: 受け入れる最低品質スコア
        allow_placeholder_ratio: placeholder 比率の許容上限

    Returns:
        SafetyResult
    """
    result = SafetyResult(passed=True)

    # 1. 法的 NG ワード
    full_text = f"{plan.caption}\n{plan.subtitle_text}\n{' '.join(plan.hashtags)}"
    violations = detect_legal_violations(full_text)
    if violations:
        result.blockers.append(f"法的NG: {', '.join(set(violations))}")

    # 2. ステマ規制(#PR / #広告 必須)
    tag_lower = {t.lower() for t in plan.hashtags}
    if "#pr" not in tag_lower:
        result.blockers.append("#PR タグ欠落")
    if "#広告" not in plan.hashtags:
        result.blockers.append("#広告 タグ欠落")

    # 3. 品質スコア
    scores = score_plan(plan)
    result.scores = scores
    if scores["total"] < min_quality_score:
        result.blockers.append(
            f"品質不足 (total={scores['total']:.2f} < {min_quality_score})"
        )

    # 4. placeholder 比率
    if total_slides > 0:
        ratio = used_placeholders / total_slides
        if ratio > allow_placeholder_ratio:
            result.blockers.append(
                f"placeholder比率超過 ({used_placeholders}/{total_slides})"
            )
        elif ratio > 0:
            result.warnings.append(
                f"placeholder 一部使用 ({used_placeholders}/{total_slides})"
            )

    # 5. 動画ファイル存在(空または極小ファイル = 生成失敗を検出)
    if video_path is not None:
        if not video_path.exists():
            result.blockers.append(f"動画ファイル不在: {video_path}")
        elif video_path.stat().st_size < 10_000:
            result.blockers.append(
                f"動画サイズ異常 ({video_path.stat().st_size} bytes)"
            )

    # 6. キャプション長さ
    if len(plan.caption) < 30:
        result.warnings.append("キャプションが短い (<30文字)")
    if len(plan.caption) > 2200:
        result.blockers.append("キャプションが TikTok 上限超過 (>2200文字)")

    # 7. 字幕の存在
    if not plan.subtitle_text.strip():
        result.blockers.append("字幕が空")

    result.passed = len(result.blockers) == 0
    if result.passed:
        logger.info(
            "セーフティゲート通過",
            warnings=result.warnings,
            quality=round(scores["total"], 3),
        )
    else:
        logger.warning(
            "セーフティゲート不通過",
            blockers=result.blockers,
            warnings=result.warnings,
        )
    return result
