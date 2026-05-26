"""Veo 単独デモ: 実物の Veo を呼んで8秒×2本の動画を生成

Claude のクレジットが無いので、プロンプトは手書きで用意。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import Settings  # noqa: E402
from src.prompt_generator.models import ContentPlan  # noqa: E402
from src.utils.logger import configure_logging, get_logger  # noqa: E402
from src.video_editor.processor import VideoProcessor  # noqa: E402
from src.video_generator.veo_client import VeoClient  # noqa: E402


def hand_crafted_plan() -> ContentPlan:
    """Claude の代わりに手書きしたプラン(衣類スチーマー商品)"""
    return ContentPlan(
        veo_prompt_clip1=(
            "Vertical 9:16, 8 seconds. Cinematic close-up of a sleek modern "
            "handheld garment steamer placed on a minimalist white studio "
            "surface. Soft warm directional light from the left. Gentle steam "
            "particles rise slowly. The camera slowly tracks in. Premium "
            "product aesthetic, clean composition, shallow depth of field. "
            "Soft ambient music."
        ),
        veo_prompt_clip2=(
            "Vertical 9:16, 8 seconds. A young woman in her 20s in a bright "
            "modern Japanese bedroom holds a sleek handheld garment steamer "
            "and effortlessly removes wrinkles from a white cotton shirt "
            "hanging on a wooden hanger. Soft morning natural light. Calm "
            "satisfying mood, warm tones, gentle close-ups of the shirt "
            "becoming smooth. Upbeat lifestyle music."
        ),
        caption=(
            "朝の5分で仕上がる、忙しい大人の衣類スチーマー✨\n"
            "ハンガーにかけたままシワも臭いもサヨナラ。\n"
            "出張・旅行のお供にもぴったり。"
        ),
        hashtags=[
            "#PR",
            "#広告",
            "#衣類スチーマー",
            "#家電",
            "#暮らしを整える",
            "#おすすめ",
            "#忙しい朝",
            "#出張グッズ",
            "#新生活",
            "#時短",
        ],
        subtitle_text="忙しい朝も\nハンガーで完了\nプロフィールから",
        bgm_mood="upbeat",
        voice_style="calm friendly",
    )


async def main() -> int:
    configure_logging()
    logger = get_logger(__name__)

    settings = Settings()  # .env から読む
    if not settings.gemini_api_key:
        print("❌ GEMINI_API_KEY が .env にありません")
        return 1

    print("\n" + "=" * 70)
    print(f"Veo モデル: {settings.veo_model}")
    print("=" * 70)

    plan = hand_crafted_plan()
    print("\n--- 🎬 Veo プロンプト #1 ---")
    print(plan.veo_prompt_clip1)
    print("\n--- 🎬 Veo プロンプト #2 ---")
    print(plan.veo_prompt_clip2)

    # Veo は本物を呼ぶ(.env の dry_run は false にしてある)
    veo_settings = Settings(dry_run=False)
    veo = VeoClient(veo_settings)

    generated_dir = veo_settings.storage_local_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print("🎥 Veo 動画生成中... (1本あたり 2〜5分、合計 4〜10 分)")
    print("=" * 70)

    start = time.time()
    try:
        clip_paths = await veo.generate_clips_for_plan(plan, generated_dir)
    except Exception as e:
        print(f"\n❌ Veo 生成失敗: {e}")
        logger.exception("Veo エラー詳細")
        return 1

    elapsed = time.time() - start
    print(f"\n✅ 動画生成完了 ({elapsed:.1f}秒)")
    for i, p in enumerate(clip_paths, 1):
        size = p.stat().st_size / 1024 / 1024 if p.exists() else 0
        print(f"  クリップ{i}: {p} ({size:.1f} MB)")

    # 動画編集(連結 + 字幕 + 広告表示)
    print("\n" + "=" * 70)
    print("📼 動画編集: 連結 → 字幕焼き込み → 「広告」表示")
    print("=" * 70)
    edit_settings = Settings(dry_run=True)  # BGM 取得を無効化
    processor = VideoProcessor(edit_settings)
    edited_dir = edit_settings.storage_local_dir / "edited"

    final = processor.process(
        clip_paths,
        plan,
        output_dir=edited_dir,
        post_id="demo_veo_real",
    )

    print(f"\n✅ 最終ファイル: {final}")
    if final.exists():
        size_mb = final.stat().st_size / 1024 / 1024
        print(f"   サイズ: {size_mb:.2f} MB")

    print("\n" + "=" * 70)
    print("🎉 完了!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
