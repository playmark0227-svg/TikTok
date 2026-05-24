"""Google Veo 3.1 動画生成クライアント

google-genai SDK で Veo にプロンプトを投げ、生成された MP4 をダウンロードする。
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from src.prompt_generator.models import ContentPlan
from src.utils.logger import get_logger

logger = get_logger(__name__)

POLL_INTERVAL = 10  # seconds
MAX_POLL_DURATION = 600  # seconds (10 minutes)


class VeoAPIError(Exception):
    """Veo API エラー"""


class VeoClient:
    """Veo 3.1 動画生成クライアント"""

    def __init__(self, settings: Settings | None = None, client: Any = None):
        self.settings = settings or get_settings()
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if self.settings.is_dry_run:
            logger.info("DRY_RUN: Veo クライアント初期化スキップ")
            self._client = "dry_run_client"
            return self._client

        try:
            from google import genai
        except ImportError as e:
            raise VeoAPIError("google-genai SDK がインストールされていません") from e

        if not self.settings.gemini_api_key:
            raise VeoAPIError("GEMINI_API_KEY が設定されていません (.env を確認)")

        self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=3, min=3, max=30),
        retry=retry_if_exception_type(VeoAPIError),
        reraise=True,
    )
    async def generate_video(
        self,
        prompt: str,
        output_path: Path,
        *,
        duration_seconds: int = 8,
        aspect_ratio: str = "9:16",
        with_audio: bool = True,
    ) -> Path:
        """1本の動画を生成

        Args:
            prompt: Veo に渡す英語プロンプト
            output_path: 保存先 MP4 パス
            duration_seconds: 1〜8 秒
            aspect_ratio: "9:16" (推奨) or "16:9"
            with_audio: 音声付き生成

        Returns:
            ダウンロード済み MP4 のパス
        """
        logger.info(
            "Veo 動画生成開始",
            duration=duration_seconds,
            aspect_ratio=aspect_ratio,
            with_audio=with_audio,
            prompt_len=len(prompt),
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.settings.is_dry_run:
            return self._dry_run_video(output_path, duration_seconds)

        client = self._get_client()
        try:
            from google.genai import types as genai_types
        except ImportError as e:
            raise VeoAPIError("google-genai SDK の types が読み込めません") from e

        config_kwargs: dict[str, Any] = {
            "aspect_ratio": aspect_ratio,
            "duration_seconds": duration_seconds,
        }
        if not with_audio:
            config_kwargs["generate_audio"] = False

        try:
            operation = client.models.generate_videos(
                model=self.settings.veo_model,
                prompt=prompt,
                config=genai_types.GenerateVideosConfig(**config_kwargs),
            )
        except Exception as e:
            logger.error("Veo 生成リクエストエラー", error=str(e))
            raise VeoAPIError(f"Veo 生成リクエスト失敗: {e}") from e

        return await self._poll_and_download(client, operation, output_path)

    async def _poll_and_download(
        self,
        client: Any,
        operation: Any,
        output_path: Path,
    ) -> Path:
        """ジョブ完了までポーリングしてダウンロード"""
        start_time = time.time()
        loop = asyncio.get_event_loop()
        while not getattr(operation, "done", False):
            if time.time() - start_time > MAX_POLL_DURATION:
                raise VeoAPIError(
                    f"Veo 生成タイムアウト ({MAX_POLL_DURATION}秒)"
                )
            await asyncio.sleep(POLL_INTERVAL)
            try:
                operation = await loop.run_in_executor(
                    None,
                    client.operations.get,
                    operation,
                )
            except Exception as e:
                raise VeoAPIError(f"Veo ポーリング失敗: {e}") from e
            logger.debug("Veo ポーリング", done=getattr(operation, "done", False))

        response = getattr(operation, "response", None)
        if response is None:
            raise VeoAPIError("Veo レスポンスが空です")

        generated_videos = getattr(response, "generated_videos", None) or []
        if not generated_videos:
            raise VeoAPIError("生成された動画が見つかりません")

        first_video = generated_videos[0].video
        try:
            await loop.run_in_executor(
                None,
                lambda: client.files.download(file=first_video),
            )
            await loop.run_in_executor(
                None,
                lambda: first_video.save(str(output_path)),
            )
        except Exception as e:
            raise VeoAPIError(f"動画ダウンロード失敗: {e}") from e

        if not output_path.exists():
            raise VeoAPIError(f"ダウンロードしたファイルが存在しません: {output_path}")

        logger.info("Veo 動画生成完了", path=str(output_path), size=output_path.stat().st_size)
        return output_path

    async def generate_clips_for_plan(
        self,
        plan: ContentPlan,
        output_dir: Path,
        *,
        per_clip_seconds: int = 8,
    ) -> list[Path]:
        """ContentPlan の2本のプロンプトから2本のクリップを生成"""
        output_dir.mkdir(parents=True, exist_ok=True)
        clip_paths = [
            output_dir / f"clip1_{int(time.time())}.mp4",
            output_dir / f"clip2_{int(time.time())}.mp4",
        ]
        # 同時生成は API レート制限考慮で逐次実行
        await self.generate_video(
            plan.veo_prompt_clip1, clip_paths[0], duration_seconds=per_clip_seconds
        )
        await self.generate_video(
            plan.veo_prompt_clip2, clip_paths[1], duration_seconds=per_clip_seconds
        )
        return clip_paths

    def _dry_run_video(self, output_path: Path, duration: int) -> Path:
        """DRY_RUN: サンプル動画をコピー、または FFmpeg で短いダミーを作る"""
        # まずプロジェクト同梱のサンプルを試す
        sample = self.settings.assets_dir / "sample_dryrun.mp4"
        if sample.exists():
            shutil.copyfile(sample, output_path)
            logger.info("DRY_RUN: サンプル動画コピー", path=str(output_path))
            return output_path

        # FFmpeg で黒一色の動画を生成
        try:
            import ffmpeg  # type: ignore[import-untyped]

            (
                ffmpeg.input(
                    f"color=c=black:s=720x1280:d={duration}",
                    f="lavfi",
                )
                .output(
                    str(output_path),
                    vcodec="libx264",
                    pix_fmt="yuv420p",
                    t=duration,
                )
                .overwrite_output()
                .run(quiet=True)
            )
        except Exception as e:
            # FFmpeg が無ければ空の MP4 (中身は0バイト) を作る
            logger.warning("DRY_RUN: FFmpegでのダミー動画生成失敗", error=str(e))
            output_path.touch()

        logger.info("DRY_RUN: ダミー動画生成", path=str(output_path), duration=duration)
        return output_path
