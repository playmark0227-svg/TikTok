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
        from src.video_generator.image_generator import ImageGenerationError
        from src.video_generator.slideshow_builder import generate_placeholder_image

        slides_dir = self.settings.storage_local_dir / "generated" / post_id
        slides_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        subtitle_lines = [
            s.strip() for s in plan.subtitle_text.split("\n") if s.strip()
        ]
        n_slides = max(
            self.settings.slideshow_slide_count, len(subtitle_lines)
        )

        base_prompt = plan.veo_prompt_clip1 or product.description
        variants = [
            "studio close-up shot",
            "lifestyle scene with natural light",
            "macro detail focus",
            "hero shot with bokeh background",
            "person using the product with happy expression",
        ]
        slide_prompts = [
            f"{base_prompt} -- shot variant {i+1}: {variants[i % len(variants)]}, "
            "vertical 9:16 portrait, photorealistic, soft cinematic lighting, "
            "no text overlay, no watermark, clean composition"
            for i in range(n_slides)
        ]

        image_paths: list[Path] = []
        placeholder_count = 0
        for i, prompt in enumerate(slide_prompts):
            img = slides_dir / f"slide_{i:02d}.png"
            try:
                self.image_gen.generate(prompt, img, aspect_ratio="9:16")
            except ImageGenerationError:
                title = (
                    subtitle_lines[i] if i < len(subtitle_lines) else product.category
                )
                sub = product.display_title[:40]
                generate_placeholder_image(img, title, sub, palette_index=i)
                placeholder_count += 1
            image_paths.append(img)

        raw_path = output_dir / f"{post_id}_raw.mp4"
        self.builder.build(image_paths, raw_path)

        # TikTok 風テロップ焼き込み
        subbed_path = output_dir / f"{post_id}_captioned.mp4"
        try:
            TikTokCaptionBurner().burn(raw_path, subbed_path, plan.subtitle_text)
            before_pr = subbed_path
        except Exception:
            before_pr = raw_path

        # 「広告」表示焼き込み(必須)
        final_path = output_dir / f"{post_id}_final.mp4"
        PROverlayBurner().burn(before_pr, final_path, label="広告")

        # 動画長さ取得
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
        )


def build_engine(settings) -> AbstractVideoEngine:
    """settings.video_mode に応じて適切なエンジンを返す"""
    mode = settings.video_mode
    if mode == "slideshow":
        return SlideshowEngine(settings)
    if mode == "veo":
        return VeoEngine(settings)
    raise ValueError(f"未知の video_mode: {mode}")
