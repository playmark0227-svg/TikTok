"""最適化後のサンプル動画レンダリング(セーフティゲートをバイパス)

billing 未有効の環境で「最適化されたコピー + テロップ + エフェクト」を確認するため、
Engine.generate() を直接呼ぶ。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import Settings  # noqa: E402
from src.product_selector.models import Product  # noqa: E402
from src.prompt_generator.models import ContentPlan  # noqa: E402
from src.utils.logger import configure_logging  # noqa: E402
from src.video_generator.engine import SlideshowEngine  # noqa: E402


async def main() -> int:
    configure_logging()

    settings = Settings(
        dry_run=False,
        content_generator="gemini",
        video_mode="slideshow",
        slideshow_slide_count=5,
        slideshow_slide_duration=2.5,
    )

    product = Product(
        source="amazon",
        product_id="B0SAMPLE001",
        title="衣類スチーマー ハンディアイロン コードレス 旅行 出張",
        description="コードレスで15秒で立ち上がる衣類スチーマー",
        price=4980,
        image_urls=[],
        review_count=1342,
        rating=4.4,
        category="家電",
        affiliate_url="https://example.com",
    )

    # 強い品質のサンプルプラン(本番では Gemini が生成する想定)
    plan = ContentPlan(
        veo_prompt_clip1="A woman struggling with wrinkled shirts in the morning",
        veo_prompt_clip2="The same woman using a sleek handheld steamer happy",
        caption=(
            "コレ知らない人マジで損してる🚨 朝のシワ伸ばし、もうアイロン使ってないんだけど。"
            "レビュー1342件超えてて在庫薄くなってきてるから、気になる人は早めに見てきて。"
            "コメ欄にリンク貼っとくね📌"
        ),
        hashtags=[
            "#PR", "#広告", "#TikTok購入品", "#知らないと損",
            "#バズり中", "#時短家電", "#一人暮らし",
            "#本当に買ってよかったもの", "#新生活",
        ],
        subtitle_text=(
            "コレ知らない?🚨\n"
            "マジで人生変わる\n"
            "アイロン捨てた\n"
            "在庫切れ続出中\n"
            "コメ欄にリンク📌"
        ),
        bgm_mood="upbeat",
        voice_style="energetic Gen-Z female",
    )

    print("\n=== 最適化サンプル動画レンダリング ===")
    print(f"  商品  : {product.display_title}")
    print(f"  字幕  : {plan.subtitle_text.replace(chr(10), ' / ')}")
    print()

    engine = SlideshowEngine(settings)
    output_dir = settings.storage_local_dir / "edited"
    result = await engine.generate(
        plan,
        product,
        output_dir=output_dir,
        post_id="sample_optimized",
    )

    print(f"\n✓ 完成: {result.video_path}")
    print(f"  サイズ  : {result.video_path.stat().st_size / 1024:.1f} KB")
    print(f"  時間    : {result.duration_seconds:.1f}s")
    print(f"  使用素材: {result.total_assets} 枚 (placeholder {result.placeholder_count})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
