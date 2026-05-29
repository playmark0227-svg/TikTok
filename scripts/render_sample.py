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


def _make_sample_product_photo(path: Path) -> Path:
    """擬似商品写真(白背景にスチーマー風シルエット)。
    本番では Amazon/楽天 の実画像 URL に置き換わる。"""
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 900, 900
    img = Image.new("RGB", (w, h), (248, 248, 250))
    d = ImageDraw.Draw(img)
    # 本体
    d.rounded_rectangle([360, 280, 540, 620], radius=40, fill=(70, 90, 160))
    # ヘッド部
    d.rounded_rectangle([330, 200, 570, 320], radius=30, fill=(90, 110, 190))
    # スチーム穴
    for cx in range(370, 540, 40):
        d.ellipse([cx, 235, cx + 16, 251], fill=(210, 220, 240))
    # ハンドル
    d.rounded_rectangle([420, 600, 480, 760], radius=24, fill=(50, 60, 110))
    # 影
    d.ellipse([330, 770, 570, 820], fill=(225, 225, 230))
    img.save(path, quality=90)
    return path


async def main() -> int:
    configure_logging()

    settings = Settings(
        dry_run=False,
        content_generator="gemini",
        video_mode="slideshow",
        slideshow_slide_count=5,
        slideshow_slide_duration=2.5,
    )

    # 実商品画像のスタンドイン(本番では Amazon/楽天 API の image_urls)
    # この環境はネットワーク遮断のため、ローカルに擬似商品写真を作り file:// で渡す
    sample_photo = _make_sample_product_photo(
        settings.storage_local_dir / "generated" / "sample_product.jpg"
    )

    product = Product(
        source="amazon",
        product_id="B0SAMPLE001",
        title="衣類スチーマー ハンディアイロン コードレス 旅行 出張",
        description="コードレスで15秒で立ち上がる衣類スチーマー",
        price=4980,
        image_urls=[f"file://{sample_photo}"],
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
