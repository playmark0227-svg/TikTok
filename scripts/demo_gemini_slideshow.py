"""Gemini + 画像スライドショー方式の実動デモ

このスクリプトは以下を実行:
1. サンプル商品(Amazon 未取得)
2. Gemini Free tier で企画生成(本物の API 呼び出し)
3. Pillow で各スライド画像を生成
4. FFmpeg で Ken Burns + クロスフェードの縦動画化
5. 「広告」表示焼き込み(ステマ規制対応)

完成した MP4 が storage_local/edited/ に出る。
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import Settings  # noqa: E402
from src.product_selector.models import Product  # noqa: E402
from src.prompt_generator.gemini_client import GeminiContentClient  # noqa: E402
from src.utils.logger import configure_logging, get_logger  # noqa: E402
from src.video_editor.pr_overlay import PROverlayBurner  # noqa: E402
from src.video_editor.subtitle_burner import SubtitleBurner  # noqa: E402
from src.video_generator.slideshow_builder import (  # noqa: E402
    SlideshowBuilder,
    generate_placeholder_image,
)


def make_sample_product() -> Product:
    return Product(
        source="amazon",
        product_id="B0DEMO001",
        title="衣類スチーマー ハンディアイロン コードレス 軽量 旅行 出張",
        description=(
            "コードレスで使える携帯型の衣類スチーマー。"
            "15秒で立ち上がり、アイロン台不要でハンガーにかけたまま使える。"
            "出張・旅行・忙しい朝の救世主。"
        ),
        price=4980,
        image_urls=[],
        review_count=1342,
        rating=4.4,
        category="家電",
        affiliate_url="https://www.amazon.co.jp/dp/B0DEMO001",
        selected_at=datetime.now(),
    )


async def main() -> int:
    configure_logging()
    logger = get_logger(__name__)
    logger.info("=== Gemini + スライドショー デモ ===")

    print("\n" + "=" * 70)
    print("[1/4] 商品(サンプル)")
    print("=" * 70)
    product = make_sample_product()
    print(f"  {product.title}")
    print(f"  カテゴリ: {product.category} / 価格: ¥{product.price:,}")
    print(f"  評価: ★{product.rating} ({product.review_count}件)")

    print("\n" + "=" * 70)
    print("[2/4] Gemini で企画生成中(本物の API 呼び出し)...")
    print("=" * 70)
    settings = Settings(dry_run=False)
    gemini = GeminiContentClient(settings, model="gemini-2.5-flash")
    plan = await gemini.generate(product)

    print(f"\n📝 キャプション:\n{plan.caption}")
    print(f"\n# ハッシュタグ:\n{' '.join(plan.hashtags)}")
    print(f"\n💬 動画字幕(スライドに表示):\n{plan.subtitle_text}")
    print(f"\n🎵 BGM ムード: {plan.bgm_mood} / 🎙 音声: {plan.voice_style}")

    print("\n" + "=" * 70)
    print("[3/4] スライド画像を生成(PIL でプレースホルダ)")
    print("=" * 70)
    storage = settings.storage_local_dir / "demo_slides"
    storage.mkdir(parents=True, exist_ok=True)

    subtitle_lines = [line.strip() for line in plan.subtitle_text.split("\n") if line.strip()]
    # スライドに使うフレーズを4つ用意
    slide_phrases = [
        (subtitle_lines[0] if len(subtitle_lines) >= 1 else "新発見", product.title[:30]),
        (subtitle_lines[1] if len(subtitle_lines) >= 2 else "便利すぎる", "コードレス・15秒で立ち上がり"),
        (subtitle_lines[2] if len(subtitle_lines) >= 3 else "プチプラ", f"¥{product.price:,} / ★{product.rating}"),
        ("プロフのリンクから", "詳細を見る ↗"),
    ]

    image_paths: list[Path] = []
    for i, (title, sub) in enumerate(slide_phrases):
        img_path = storage / f"slide_{i:02d}.png"
        generate_placeholder_image(img_path, title, sub)
        print(f"  生成: {img_path.name} - 「{title}」")
        image_paths.append(img_path)

    print("\n" + "=" * 70)
    print("[4/4] FFmpeg で動画化 (Ken Burns + クロスフェード + 広告表示)")
    print("=" * 70)
    edited_dir = settings.storage_local_dir / "edited"
    edited_dir.mkdir(parents=True, exist_ok=True)

    # スライドショー本体
    builder = SlideshowBuilder(slide_duration=3.0, transition_duration=0.6)
    slideshow_mp4 = edited_dir / "demo_slideshow_raw.mp4"
    builder.build(image_paths, slideshow_mp4)
    print(f"  ✓ スライドショー: {slideshow_mp4.name}")

    # 字幕焼き込み
    subtitled_mp4 = edited_dir / "demo_slideshow_subtitled.mp4"
    subtitle_burner = SubtitleBurner()
    try:
        subtitle_burner.burn(slideshow_mp4, subtitled_mp4, plan.subtitle_text)
        print(f"  ✓ 字幕焼き込み: {subtitled_mp4.name}")
        before_overlay = subtitled_mp4
    except Exception as e:
        logger.warning("字幕焼き込み失敗、スキップ", error=str(e))
        before_overlay = slideshow_mp4

    # 「広告」表示焼き込み(ステマ規制対応)
    final_mp4 = edited_dir / "demo_slideshow_final.mp4"
    pr_burner = PROverlayBurner()
    pr_burner.burn(before_overlay, final_mp4, label="広告")
    print(f"  ✓ 広告表示: {final_mp4.name}")

    # JSON 保存
    json_path = edited_dir / "demo_plan.json"
    json_path.write_text(
        json.dumps(
            {
                "product": {
                    "title": product.title,
                    "category": product.category,
                    "price": product.price,
                    "rating": product.rating,
                    "review_count": product.review_count,
                },
                "plan": {
                    "caption": plan.caption,
                    "hashtags": plan.hashtags,
                    "subtitle_text": plan.subtitle_text,
                    "bgm_mood": plan.bgm_mood,
                    "full_caption_for_tiktok": plan.full_caption,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n" + "=" * 70)
    print("✅ 完了")
    print("=" * 70)
    final_size_kb = final_mp4.stat().st_size / 1024
    print(f"📹 最終動画: {final_mp4}")
    print(f"   サイズ  : {final_size_kb:.1f} KB")
    print(f"📄 企画 JSON: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
