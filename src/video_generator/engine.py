"""動画生成エンジンの抽象化(Strategy パターン)

VeoEngine / SlideshowEngine / 将来の SoraEngine / RunwayEngine 等を
同じインターフェイスで扱えるようにする。

Pipeline 側は AbstractVideoEngine だけ知っていれば良い。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from src.product_selector.models import Product
from src.prompt_generator.models import ContentPlan
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class VideoGenerationResult:
    """エンジンの生成結果"""

    video_path: Path
    placeholder_count: int = 0
    total_assets: int = 0
    engine_name: str = ""
    duration_seconds: float = 0.0
    meta: dict = field(default_factory=dict)


class AbstractVideoEngine(ABC):
    """動画生成エンジンの基底"""

    name: str = "abstract"

    @abstractmethod
    async def generate(
        self,
        plan: ContentPlan,
        product: Product,
        *,
        output_dir: Path,
        post_id: str,
    ) -> VideoGenerationResult:
        """動画を生成して最終 MP4 のパスを返す

        最終 MP4 は字幕焼き込み・広告表示まで含めた完成状態。
        Pipeline 側は受け取った video_path を Storage アップロードできる。
        """


class VeoEngine(AbstractVideoEngine):
    """Google Veo 3.1 で動画生成"""

    name = "veo"

    def __init__(self, settings, veo_client=None, processor=None):
        from src.video_editor.processor import VideoProcessor
        from src.video_generator.veo_client import VeoClient

        self.settings = settings
        self.veo = veo_client or VeoClient(settings)
        self.processor = processor or VideoProcessor(settings)

    async def generate(
        self,
        plan: ContentPlan,
        product: Product,
        *,
        output_dir: Path,
        post_id: str,
    ) -> VideoGenerationResult:
        generated_dir = self.settings.storage_local_dir / "generated"
        clips = await self.veo.generate_clips_for_plan(plan, generated_dir)
        final = self.processor.process(
            clips, plan, output_dir=output_dir, post_id=post_id
        )
        return VideoGenerationResult(
            video_path=final,
            placeholder_count=0,
            total_assets=len(clips),
            engine_name=self.name,
        )


class SlideshowEngine(AbstractVideoEngine):
    """画像スライドショー方式(Gemini 画像生成 + FFmpeg)"""

    name = "slideshow"

    def __init__(self, settings, image_generator=None, builder=None):
        from src.video_generator.image_generator import GeminiImageGenerator
        from src.video_generator.slideshow_builder import SlideshowBuilder

        self.settings = settings
        self.image_gen = image_generator or GeminiImageGenerator(settings)
        self.builder = builder or SlideshowBuilder(
            slide_duration=settings.slideshow_slide_duration,
            transition_duration=settings.slideshow_transition_duration,
        )

    async def generate(
        self,
        plan: ContentPlan,
        product: Product,
        *,
        output_dir: Path,
        post_id: str,
    ) -> VideoGenerationResult:
        from src.video_editor.pr_overlay import PROverlayBurner
        from src.video_editor.tiktok_caption import TikTokCaptionBurner

        slides_dir = self.settings.storage_local_dir / "generated" / post_id
        slides_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        subtitle_lines = [
            s.strip() for s in plan.subtitle_text.split("\n") if s.strip()
        ]
        n_slides = max(self.settings.slideshow_slide_count, len(subtitle_lines))

        # スライド画像を用意(優先順: 実商品画像 → AI生成 → placeholder)
        image_paths, placeholder_count = self._prepare_slide_images(
            plan, product, slides_dir, n_slides, subtitle_lines
        )

        raw_path = output_dir / f"{post_id}_raw.mp4"
        self.builder.build(image_paths, raw_path)

        # TikTok 風テロップ焼き込み
        subbed_path = output_dir / f"{post_id}_captioned.mp4"
        try:
            TikTokCaptionBurner().burn(raw_path, subbed_path, plan.subtitle_text)
            before_pr = subbed_path
        except Exception:
            before_pr = raw_path

        # BGM ミックス(assets にあればそれ、無ければ合成)
        with_bgm = self._add_bgm(before_pr, plan, output_dir, post_id)

        # 「広告」表示焼き込み(必須)
        final_path = output_dir / f"{post_id}_final.mp4"
        PROverlayBurner().burn(with_bgm, final_path, label="広告")

        from src.video_editor.ffmpeg_wrapper import FFmpegWrapper

        try:
            duration = FFmpegWrapper().get_duration(final_path)
        except Exception:
            duration = 0.0

        return VideoGenerationResult(
            video_path=final_path,
            placeholder_count=placeholder_count,
            total_assets=n_slides,
            engine_name=self.name,
            duration_seconds=duration,
            meta={"image_source": self._last_image_source},
        )

    _last_image_source = "unknown"

    def _prepare_slide_images(
        self, plan, product, slides_dir: Path, n_slides: int, subtitle_lines: list[str]
    ) -> tuple[list[Path], int]:
        """スライド画像を用意。優先順: ①実商品画像 → ②AI生成 → ③placeholder"""
        from src.video_generator.image_generator import ImageGenerationError
        from src.video_generator.product_slide import (
            ProductImageError,
            compose_product_slide,
            download_image,
        )
        from src.video_generator.slideshow_builder import generate_placeholder_image

        image_paths: list[Path] = []
        placeholder_count = 0

        # ① 実商品画像があれば、それをベースに合成(最優先・無料・商品が映る)
        product_imgs: list[Path] = []
        for j, url in enumerate(product.image_urls[:n_slides]):
            dst = slides_dir / f"src_{j:02d}.jpg"
            try:
                download_image(url, dst)
                product_imgs.append(dst)
            except ProductImageError as e:
                logger.warning("商品画像DL失敗", url=url[:50], error=str(e))

        if product_imgs:
            self._last_image_source = "product_photo"
            # テキストは TikTokCaptionBurner が行ごとアニメで載せるので、
            # スライドには焼かない(headline_baked=False)= 二重表示を防ぐ
            for i in range(n_slides):
                base_img = product_imgs[i % len(product_imgs)]
                slide = slides_dir / f"slide_{i:02d}.png"
                try:
                    compose_product_slide(
                        base_img, slide, headline="", accent_index=i,
                        headline_baked=False,
                    )
                except ProductImageError:
                    headline = (
                        subtitle_lines[i] if i < len(subtitle_lines) else product.category
                    )
                    generate_placeholder_image(slide, headline, "", palette_index=i)
                    placeholder_count += 1
                image_paths.append(slide)
            return image_paths, placeholder_count

        # ② 実画像が無ければ AI 生成を試す
        base_prompt = plan.veo_prompt_clip1 or product.description
        variants = [
            "studio close-up shot", "lifestyle scene with natural light",
            "macro detail focus", "hero shot with bokeh background",
            "person using the product with happy expression",
        ]
        self._last_image_source = "ai_generated"
        for i in range(n_slides):
            prompt = (
                f"{base_prompt} -- shot variant {i+1}: {variants[i % len(variants)]}, "
                "vertical 9:16 portrait, photorealistic, soft cinematic lighting, "
                "no text overlay, no watermark, clean composition"
            )
            img = slides_dir / f"slide_{i:02d}.png"
            try:
                self.image_gen.generate(prompt, img, aspect_ratio="9:16")
            except ImageGenerationError:
                # ③ 最終フォールバック: 装飾 placeholder
                self._last_image_source = "placeholder"
                title = subtitle_lines[i] if i < len(subtitle_lines) else product.category
                generate_placeholder_image(
                    img, title, product.display_title[:40], palette_index=i
                )
                placeholder_count += 1
            image_paths.append(img)
        return image_paths, placeholder_count

    def _add_bgm(self, video: Path, plan, output_dir: Path, post_id: str) -> Path:
        """BGM を付与。assets/bgm/<mood>/ にあればそれ、無ければ合成。"""
        import random

        from src.video_generator.bgm_synth import (
            BGMSynthError,
            mix_bgm_into_video,
            synthesize_bgm,
        )

        bgm_dir = self.settings.assets_dir / "bgm" / plan.bgm_mood
        candidates: list[Path] = []
        if bgm_dir.exists():
            for ext in ("*.mp3", "*.wav", "*.m4a", "*.aac"):
                candidates.extend(bgm_dir.glob(ext))

        out = output_dir / f"{post_id}_bgm.mp4"
        try:
            from src.video_editor.ffmpeg_wrapper import FFmpegWrapper

            duration = FFmpegWrapper().get_duration(video)
            if candidates:
                bgm = random.choice(candidates)
                logger.info("BGM: assets から使用", file=bgm.name)
            else:
                bgm = output_dir / f"{post_id}_synth_bgm.aac"
                synthesize_bgm(bgm, duration, mood=plan.bgm_mood)
                logger.info("BGM: 合成音を使用", mood=plan.bgm_mood)
            # 合成音は元動画が実質無音なので前面で(0.9)、実 BGM もしっかり聞かせる
            mix_bgm_into_video(video, bgm, out, bgm_volume=0.9)
            return out
        except (BGMSynthError, Exception) as e:
            logger.warning("BGM 付与失敗、スキップ", error=str(e))
            return video


def build_engine(settings) -> AbstractVideoEngine:
    """settings.video_mode に応じて適切なエンジンを返す"""
    mode = settings.video_mode
    if mode == "slideshow":
        return SlideshowEngine(settings)
    if mode == "veo":
        return VeoEngine(settings)
    raise ValueError(f"未知の video_mode: {mode}")
