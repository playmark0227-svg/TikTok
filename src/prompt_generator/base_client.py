"""ContentPlan 生成クライアントの共通基底

Claude / Gemini など複数の LLM プロバイダで共有するロジック:
- generate / generate_best_of / revise
- JSON パース・#PR/#広告 強制・DRY_RUN ダミー

プロバイダ固有部分は _call_llm() のみサブクラスで実装する。
"""

from __future__ import annotations

import abc
import json
import re

from src.product_selector.models import Product
from src.prompt_generator.models import ContentPlan
from src.prompt_generator.templates import build_prompt, build_revision_prompt
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_TOKENS = 4096
TEMPERATURE = 0.8
VALID_BGM_MOODS = ("upbeat", "calm", "trendy")


class ContentGenerationError(Exception):
    """企画生成エラー(プロバイダ非依存)"""


class PromptParseError(Exception):
    """LLM レスポンスの JSON パース失敗"""


class BaseContentClient(abc.ABC):
    """ContentPlan 生成の共通ロジック"""

    #: ログ等で使うプロバイダ名
    provider_name: str = "llm"

    def __init__(self, settings, client=None):
        from config.settings import get_settings

        self.settings = settings or get_settings()
        self._client = client

    # ----- サブクラスが実装する部分 -----

    @abc.abstractmethod
    def _get_client(self):
        """プロバイダの SDK クライアントを返す(遅延初期化)"""

    @abc.abstractmethod
    def _call_llm(self, user_prompt: str) -> str:
        """system prompt + user prompt を送り、レスポンス文字列を返す"""

    # ----- 共通ロジック -----

    async def generate(
        self,
        product: Product,
        *,
        few_shot_examples: list[dict] | None = None,
    ) -> ContentPlan:
        """商品から ContentPlan を生成(単一案)"""
        logger.info(
            "企画生成開始",
            provider=self.provider_name,
            product_id=product.product_id,
            title=product.display_title,
        )
        if self.settings.is_dry_run:
            return self._dry_run_plan(product)

        user_prompt = build_prompt(product, few_shot_examples)
        response_text = self._call_llm(user_prompt)
        plan = self._parse_response(response_text)
        logger.info(
            "企画生成完了",
            provider=self.provider_name,
            caption_len=len(plan.caption),
            hashtag_count=len(plan.hashtags),
        )
        return plan

    async def generate_best_of(
        self,
        product: Product,
        *,
        n: int = 3,
        few_shot_examples: list[dict] | None = None,
    ) -> ContentPlan:
        """N 案生成して品質スコア最高のものを返す"""
        from src.prompt_generator.quality_scorer import score_plan

        if self.settings.is_dry_run or n <= 1:
            return await self.generate(product, few_shot_examples=few_shot_examples)

        candidates: list[tuple[ContentPlan, dict]] = []
        for i in range(n):
            try:
                plan = await self.generate(product, few_shot_examples=few_shot_examples)
                scores = score_plan(plan)
                candidates.append((plan, scores))
                logger.info(
                    "候補スコア",
                    provider=self.provider_name,
                    iteration=i + 1,
                    total=round(scores["total"], 3),
                    safe=bool(scores["is_safe"]),
                )
            except Exception as e:
                logger.warning("候補生成失敗", iteration=i + 1, error=str(e))

        if not candidates:
            raise ContentGenerationError("全候補生成失敗")

        safe = [(p, s) for p, s in candidates if s["is_safe"]]
        pool = safe if safe else candidates
        pool.sort(key=lambda x: x[1]["total"], reverse=True)
        best_plan, best_score = pool[0]
        logger.info(
            "ベスト案選定",
            total=round(best_score["total"], 3),
            from_n=len(candidates),
        )
        return best_plan

    async def revise(
        self,
        product: Product,
        previous_plan: ContentPlan,
        feedback: str,
    ) -> ContentPlan:
        """フィードバックを反映して再生成"""
        logger.info(
            "企画修正",
            provider=self.provider_name,
            product_id=product.product_id,
            revision=previous_plan.revision_count + 1,
        )
        if self.settings.is_dry_run:
            plan = self._dry_run_plan(product)
            plan.revision_count = previous_plan.revision_count + 1
            plan.caption = f"[修正版 v{plan.revision_count}] {plan.caption}"
            return plan

        previous_json = json.dumps(
            {
                "veo_prompt_clip1": previous_plan.veo_prompt_clip1,
                "veo_prompt_clip2": previous_plan.veo_prompt_clip2,
                "caption": previous_plan.caption,
                "hashtags": previous_plan.hashtags,
                "subtitle_text": previous_plan.subtitle_text,
                "bgm_mood": previous_plan.bgm_mood,
            },
            ensure_ascii=False,
            indent=2,
        )
        user_prompt = build_revision_prompt(product, previous_json, feedback)
        response_text = self._call_llm(user_prompt)
        plan = self._parse_response(response_text)
        plan.revision_count = previous_plan.revision_count + 1
        return plan

    # ----- パース系(static で再利用可能) -----

    def _parse_response(self, response_text: str) -> ContentPlan:
        json_str = self._extract_json(response_text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error("JSON パース失敗", response=response_text[:500])
            raise PromptParseError(f"レスポンスを JSON にパースできません: {e}") from e

        try:
            hashtags = data["hashtags"]
            if isinstance(hashtags, str):
                hashtags = [h.strip() for h in hashtags.split() if h.strip()]
            normalized_tags = self._ensure_pr_tags(hashtags)

            bgm = data.get("bgm_mood", "upbeat")
            if bgm not in VALID_BGM_MOODS:
                bgm = "upbeat"

            return ContentPlan(
                veo_prompt_clip1=data["veo_prompt_clip1"],
                veo_prompt_clip2=data["veo_prompt_clip2"],
                caption=data["caption"],
                hashtags=normalized_tags,
                subtitle_text=data["subtitle_text"],
                bgm_mood=bgm,
                voice_style=data.get("voice_style", "energetic"),
                raw_response=response_text,
            )
        except KeyError as e:
            raise PromptParseError(f"必須フィールドが不足: {e}") from e

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence_match:
            return fence_match.group(1)
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            return brace_match.group(0)
        return text

    @staticmethod
    def _ensure_pr_tags(tags: list[str]) -> list[str]:
        """#PR と #広告 を必ず含める(ステマ規制対応)"""
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            t = tag.strip()
            if not t:
                continue
            if not t.startswith("#"):
                t = "#" + t
            lower = t.lower()
            if lower in seen:
                continue
            seen.add(lower)
            normalized.append(t)

        if "#pr" not in {t.lower() for t in normalized}:
            normalized.insert(0, "#PR")
        if "#広告" not in normalized:
            normalized.insert(1, "#広告")
        return normalized

    def _dry_run_plan(self, product: Product) -> ContentPlan:
        """DRY_RUN 用ダミー企画(本番品質のサンプル)"""
        return ContentPlan(
            veo_prompt_clip1=(
                f"A vertical 9:16 video, 8 seconds. A young woman in her 20s reacts with "
                f"frustration trying to do {product.category}-related task the old way. "
                "Quick zoom into her face showing the problem. Modern bright room."
            ),
            veo_prompt_clip2=(
                "A vertical 9:16 video, 8 seconds. The same woman tries a sleek modern "
                "product (no visible brand). Smooth result, satisfied smile. "
                "Bright natural light, upbeat music synced to cuts."
            ),
            caption=(
                f"コレ知らない人マジで損してる🚨 レビュー{product.review_count}件超えの"
                f"{product.category}、買ってからもう手放せない。在庫薄くなってきてるから"
                "気になる人は早めに見てきて。コメ欄にリンク貼っとくね📌"
            ),
            hashtags=[
                "#PR", "#広告", f"#{product.category}", "#TikTok購入品",
                "#知らないと損", "#本当に買ってよかったもの", "#バズり中",
                "#時短", "#一人暮らし", "#新生活",
            ],
            subtitle_text="コレ知らない?🚨\nマジで人生変わる\n在庫切れ続出中\nコメ欄にリンク",
            bgm_mood="upbeat",
            voice_style="energetic Gen-Z female narrator",
            raw_response="[DRY_RUN] dummy plan",
        )
