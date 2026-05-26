"""Claude API デモ: 実物の Claude を呼んで企画(キャプション・Veo英語プロンプト・ハッシュタグ)を生成

Veo は API キーが無い前提で DRY_RUN(黒画面ダミー動画)で進める。
このスクリプトは Amazon / 楽天 / Firebase / TikTok 全部スキップ可能。
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
from src.prompt_generator.claude_client import ClaudeContentClient  # noqa: E402
from src.utils.logger import configure_logging, get_logger  # noqa: E402
from src.video_editor.processor import VideoProcessor  # noqa: E402
from src.video_generator.veo_client import VeoClient  # noqa: E402


def make_sample_product() -> Product:
    """Amazon/楽天 が無いのでリアルな商品例を手で用意"""
    return Product(
        source="amazon",
        product_id="B0SAMPLE001",
        title="衣類スチーマー ハンディアイロン コードレス 軽量 アイロン 旅行 出張 ワイシャツ",
        description=(
            "コードレスで使える携帯型の衣類スチーマー。15秒で立ち上がり、"
            "アイロン台不要でハンガーにかけたまま使える。出張・旅行・忙しい朝に。"
            "シワ伸ばしと除菌・消臭が同時にできる。"
        ),
        price=4980,
        image_urls=[],
        review_count=1342,
        rating=4.4,
        category="家電",
        affiliate_url="https://www.amazon.co.jp/dp/B0SAMPLE001",
        selected_at=datetime.now(),
    )


async def main() -> int:
    configure_logging()
    logger = get_logger(__name__)
    logger.info("=== Claude 実 API デモ開始 ===")

    print("\n" + "=" * 70)
    print("商品選定(Amazon/楽天 API 未設定のためサンプル使用)")
    print("=" * 70)
    product = make_sample_product()
    print(f"  タイトル : {product.title}")
    print(f"  カテゴリ : {product.category}")
    print(f"  価格     : ¥{product.price:,}")
    print(f"  評価     : ★{product.rating} ({product.review_count}件のレビュー)")
    print(f"  説明     : {product.description}")

    # Claude は dry_run=False で本物を呼ぶ
    print("\n" + "=" * 70)
    print("企画生成(Claude Opus 4.7 を実呼び出し)...")
    print("=" * 70)
    claude_settings = Settings(dry_run=False)  # .env から API キーを読む
    claude = ClaudeContentClient(claude_settings)

    plan = await claude.generate(product)

    print("\n--- 🎬 Veo プロンプト #1(動画1本目, 8秒, 英語) ---")
    print(plan.veo_prompt_clip1)

    print("\n--- 🎬 Veo プロンプト #2(動画2本目, 8秒, 英語) ---")
    print(plan.veo_prompt_clip2)

    print("\n--- 📝 TikTok キャプション(日本語) ---")
    print(plan.caption)

    print("\n--- # ハッシュタグ ---")
    print(" ".join(plan.hashtags))

    print("\n--- 💬 動画字幕(焼き込み用) ---")
    print(plan.subtitle_text)

    print(f"\n--- 🎵 BGM ムード     : {plan.bgm_mood}")
    print(f"--- 🎙 音声スタイル   : {plan.voice_style}")

    # Veo は dry_run=True で黒画面ダミー(Gemini キーがないので)
    print("\n" + "=" * 70)
    print("動画生成(Veo)")
    print("=" * 70)
    veo_settings = Settings(dry_run=True)
    veo = VeoClient(veo_settings)
    generated_dir = veo_settings.storage_local_dir / "generated"
    clip_paths = await veo.generate_clips_for_plan(plan, generated_dir)
    print(f"  クリップ1 : {clip_paths[0]}")
    print(f"  クリップ2 : {clip_paths[1]}")
    print("  ※ Gemini API キーが無いため、Veo は黒画面ダミーを生成中")

    # 動画編集(連結+字幕焼き込み+広告表示)は実際の FFmpeg を使う
    print("\n" + "=" * 70)
    print("動画編集(連結+字幕+「広告」表示焼き込み)")
    print("=" * 70)
    edit_settings = Settings(dry_run=True)  # BGM 取得を期待しない
    processor = VideoProcessor(edit_settings)
    edited_dir = edit_settings.storage_local_dir / "edited"
    final = processor.process(
        clip_paths,
        plan,
        output_dir=edited_dir,
        post_id="demo_real_claude",
    )
    print(f"  最終ファイル: {final}")
    size_kb = final.stat().st_size / 1024
    print(f"  サイズ      : {size_kb:.1f} KB")

    print("\n" + "=" * 70)
    print("✅ 完了")
    print("=" * 70)
    print(
        "・キャプション・プロンプト・ハッシュタグ → Claude が本物の応答を返した"
    )
    print(
        "・動画 → Gemini キーが無いので黒画面ダミー。実 Veo を使えばここに本物の映像が入る"
    )
    print(
        "・「広告」表示焼き込みは実 FFmpeg で実行(ステマ規制対応コードが動く証拠)"
    )

    # JSON でも保存(チャットに送る用)
    output_json = edited_dir / "demo_plan.json"
    output_json.write_text(
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
                    "veo_prompt_clip1": plan.veo_prompt_clip1,
                    "veo_prompt_clip2": plan.veo_prompt_clip2,
                    "caption": plan.caption,
                    "hashtags": plan.hashtags,
                    "subtitle_text": plan.subtitle_text,
                    "bgm_mood": plan.bgm_mood,
                    "voice_style": plan.voice_style,
                    "full_caption_for_tiktok": plan.full_caption,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n📄 JSON 保存: {output_json}")
    print(f"📹 動画保存 : {final}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
