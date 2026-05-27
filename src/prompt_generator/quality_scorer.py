"""ContentPlan の品質スコアリング(複数案からベストを選ぶための)"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.prompt_generator.models import ContentPlan

# TikTok でバズるコピーに含まれがちなパワーワード
POWER_WORDS = [
    "マジ", "ガチ", "神", "ヤバい", "ヤバ", "最強", "もう戻れない",
    "コレ無いと", "手放せない", "在庫切れ", "完売", "売り切れ続出",
    "人生変わ", "革命", "知らないと", "衝撃", "驚愕", "保存推奨",
    "リアル", "正直", "ぶっちゃけ", "クセになる", "沼", "ハマる",
    "推し", "リピ", "リピート", "買ってよかった", "持っててよかった",
]

# 薬機法・景表法 NG パターン
LEGAL_NG_PATTERNS = [
    r"絶対",
    r"100\s*%",
    r"必ず効",
    r"確実に痩せ",
    r"業界\s*No\.?\s*1",
    r"最安値",
    r"最高峰",
    r"完治",
    r"治る",
    r"病気を予防",
    r"医療効果",
    r"シミが消える",
    r"シワが消える",
    r"白髪が黒く",
]

# 弱いコピー(出されたら減点)
WEAK_PATTERNS = [
    r"便利です",
    r"おすすめです",
    r"ぜひ",
    r"いかがでしょうか",
]


@dataclass
class CopyScore:
    """コピー品質スコア (0.0〜1.0)"""

    hook_strength: float = 0.0  # フックの強さ
    emotion_density: float = 0.0  # 感情語密度
    structure_quality: float = 0.0  # CTA・構造の良さ
    legal_safety: float = 1.0  # 法的安全性(NG ワード無いほど高い)
    weakness_penalty: float = 0.0  # 弱い表現で減点
    total: float = 0.0

    @property
    def is_safe(self) -> bool:
        return self.legal_safety >= 0.95

    @property
    def is_acceptable(self) -> bool:
        """投稿許可ライン"""
        return self.is_safe and self.total >= 0.4


def score_caption(caption: str) -> CopyScore:
    """キャプション単体のスコア計算"""
    score = CopyScore()

    # 法的 NG ワード(最重要)
    legal_violations = sum(
        1 for pat in LEGAL_NG_PATTERNS if re.search(pat, caption)
    )
    score.legal_safety = max(0.0, 1.0 - legal_violations * 0.5)

    # フック判定(冒頭30字に強い表現があるか)
    head = caption[:30]
    hook_signals = [
        "?",  # 疑問符
        "!",  # 感嘆
        "🚨", "⚠️", "👀", "🔥",  # アテンション絵文字
        "知ってる", "知らない", "もう", "ガチで", "マジで",
        "衝撃", "在庫", "完売", "見て",
    ]
    hook_hits = sum(1 for s in hook_signals if s in head)
    score.hook_strength = min(1.0, hook_hits * 0.35)

    # 感情語密度
    power_hits = sum(1 for w in POWER_WORDS if w in caption)
    score.emotion_density = min(1.0, power_hits * 0.25)

    # 構造(CTA表現が含まれるか)
    cta_signals = [
        "リンク", "プロフ", "保存", "コメ欄",
        "見て", "試して", "チェック", "ストーリー",
    ]
    cta_hits = sum(1 for s in cta_signals if s in caption)
    score.structure_quality = min(1.0, cta_hits * 0.4)

    # 弱表現減点
    weak_hits = sum(1 for pat in WEAK_PATTERNS if re.search(pat, caption))
    score.weakness_penalty = min(0.5, weak_hits * 0.15)

    # 合計(重み付き)
    raw = (
        score.hook_strength * 0.35
        + score.emotion_density * 0.30
        + score.structure_quality * 0.20
        + score.legal_safety * 0.15
    )
    score.total = max(0.0, raw - score.weakness_penalty)
    return score


def score_subtitle(subtitle: str) -> float:
    """字幕の品質スコア(0.0〜1.0)"""
    lines = [line.strip() for line in subtitle.split("\n") if line.strip()]
    if not lines:
        return 0.0

    # 行数(3〜5行が理想)
    n = len(lines)
    line_count_score = 1.0 if 3 <= n <= 5 else 0.5 if n in (2, 6) else 0.2

    # 各行の長さ(5〜12字が理想)
    length_scores = []
    for line in lines:
        if 5 <= len(line) <= 12:
            length_scores.append(1.0)
        elif len(line) <= 18:
            length_scores.append(0.6)
        else:
            length_scores.append(0.2)
    length_score = sum(length_scores) / len(length_scores)

    # パワーワード
    full = " ".join(lines)
    power_hits = sum(1 for w in POWER_WORDS if w in full)
    power_score = min(1.0, power_hits * 0.4)

    return line_count_score * 0.3 + length_score * 0.4 + power_score * 0.3


def score_plan(plan: ContentPlan) -> dict[str, float]:
    """ContentPlan 全体のスコアリング"""
    cap_score = score_caption(plan.caption)
    sub_score = score_subtitle(plan.subtitle_text)
    hashtag_score = _score_hashtags(plan.hashtags)

    total = cap_score.total * 0.5 + sub_score * 0.3 + hashtag_score * 0.2
    return {
        "caption_total": cap_score.total,
        "caption_hook": cap_score.hook_strength,
        "caption_emotion": cap_score.emotion_density,
        "caption_cta": cap_score.structure_quality,
        "caption_legal": cap_score.legal_safety,
        "subtitle": sub_score,
        "hashtags": hashtag_score,
        "total": total,
        "is_safe": float(cap_score.is_safe),
        "is_acceptable": float(cap_score.is_acceptable and total >= 0.4),
    }


def _score_hashtags(tags: list[str]) -> float:
    """ハッシュタグの品質スコア"""
    if not tags:
        return 0.0
    has_pr = any("#PR" == t or "#pr" == t.lower() for t in tags)
    has_ad = "#広告" in tags
    if not (has_pr and has_ad):
        return 0.0  # 規制違反
    if 8 <= len(tags) <= 12:
        return 1.0
    if 5 <= len(tags) < 8 or 12 < len(tags) <= 15:
        return 0.7
    return 0.4


def detect_legal_violations(text: str) -> list[str]:
    """違反パターンを列挙"""
    matches: list[str] = []
    for pat in LEGAL_NG_PATTERNS:
        m = re.search(pat, text)
        if m:
            matches.append(m.group(0))
    return matches
