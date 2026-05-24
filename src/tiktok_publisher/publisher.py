"""TikTok Content Posting API クライアント

Direct Post (PULL_FROM_URL) で投稿する。
事前に TikTok 審査通過が必要。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from src.product_selector.models import Product
from src.prompt_generator.models import ContentPlan
from src.tiktok_publisher.oauth import TikTokOAuthManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

CREATOR_INFO_ENDPOINT = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
PUBLISH_INIT_ENDPOINT = "https://open.tiktokapis.com/v2/post/publish/video/init/"
PUBLISH_STATUS_ENDPOINT = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
REQUEST_TIMEOUT = 30.0
MAX_CAPTION_LENGTH = 2200  # TikTok の上限
STATUS_POLL_INTERVAL = 5.0
STATUS_MAX_DURATION = 600.0


class TikTokPublishError(Exception):
    """TikTok 投稿エラー"""


@dataclass
class PublishResult:
    """投稿結果"""

    success: bool
    publish_id: str = ""
    tiktok_video_id: str = ""
    tiktok_url: str = ""
    error_message: str = ""
    posted_at: datetime | None = None


class TikTokPublisher:
    """TikTok Content Posting API 投稿クライアント"""

    def __init__(
        self,
        settings: Settings | None = None,
        oauth_manager: TikTokOAuthManager | None = None,
    ):
        self.settings = settings or get_settings()
        self.oauth = oauth_manager or TikTokOAuthManager(self.settings)

    def build_caption(self, plan: ContentPlan, _product: Product | None = None) -> str:
        """TikTok 用キャプションを組み立てる"""
        caption = plan.full_caption
        if len(caption) > MAX_CAPTION_LENGTH:
            caption = caption[: MAX_CAPTION_LENGTH - 3] + "..."
        return caption

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception_type((TikTokPublishError, httpx.HTTPError)),
        reraise=True,
    )
    async def publish_from_url(
        self,
        video_url: str,
        plan: ContentPlan,
        product: Product,
    ) -> PublishResult:
        """PULL_FROM_URL 方式で投稿"""
        logger.info(
            "TikTok 投稿開始",
            video_url=video_url[:80] + "...",
            product_id=product.product_id,
        )

        if self.settings.skip_tiktok_post:
            logger.warning("SKIP_TIKTOK_POST=true のため、投稿スキップ")
            return PublishResult(
                success=True,
                publish_id="skipped",
                tiktok_url="(skipped)",
                posted_at=datetime.now(),
            )

        if self.settings.is_dry_run:
            return self._dry_run_publish(plan, product)

        # 1. クリエイター情報取得 (オプション、Direct Post 用にプライバシー設定の確認)
        access_token = await self.oauth.get_valid_access_token()
        creator_info = await self._fetch_creator_info(access_token)
        privacy_level = self._pick_privacy_level(creator_info)

        # 2. 投稿初期化
        caption = self.build_caption(plan, product)
        publish_id = await self._init_publish(
            access_token=access_token,
            video_url=video_url,
            caption=caption,
            privacy_level=privacy_level,
        )

        # 3. ステータスポーリング
        return await self._poll_status(access_token, publish_id)

    async def _fetch_creator_info(self, access_token: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    CREATOR_INFO_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json; charset=UTF-8",
                    },
                    json={},
                )
                response.raise_for_status()
                return response.json().get("data", {})
        except httpx.HTTPError as e:
            logger.warning("クリエイター情報取得失敗、デフォルト設定で続行", error=str(e))
            return {}

    @staticmethod
    def _pick_privacy_level(creator_info: dict) -> str:
        options = creator_info.get("privacy_level_options") or []
        # 推奨順
        for pref in ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"):
            if pref in options:
                return pref
        return "PUBLIC_TO_EVERYONE"

    async def _init_publish(
        self,
        *,
        access_token: str,
        video_url: str,
        caption: str,
        privacy_level: str,
    ) -> str:
        payload = {
            "post_info": {
                "title": caption,
                "privacy_level": privacy_level,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    PUBLISH_INIT_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json; charset=UTF-8",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "TikTok 投稿初期化HTTPエラー",
                status=e.response.status_code,
                body=e.response.text[:500],
            )
            raise TikTokPublishError(
                f"投稿初期化失敗: {e.response.status_code}"
            ) from e

        if data.get("error", {}).get("code") not in ("ok", "", None):
            raise TikTokPublishError(
                f"TikTok エラー: {data.get('error', {}).get('message', 'unknown')}"
            )

        publish_id = data.get("data", {}).get("publish_id")
        if not publish_id:
            raise TikTokPublishError(f"publish_id が取得できません: {data}")
        return publish_id

    async def _poll_status(self, access_token: str, publish_id: str) -> PublishResult:
        loop_start = asyncio.get_event_loop().time()
        attempts = 0

        while True:
            if asyncio.get_event_loop().time() - loop_start > STATUS_MAX_DURATION:
                raise TikTokPublishError(
                    f"投稿ステータスポーリングタイムアウト ({STATUS_MAX_DURATION}秒)"
                )

            await asyncio.sleep(STATUS_POLL_INTERVAL)
            attempts += 1

            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    response = await client.post(
                        PUBLISH_STATUS_ENDPOINT,
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json; charset=UTF-8",
                        },
                        json={"publish_id": publish_id},
                    )
                    response.raise_for_status()
                    data = response.json()
            except httpx.HTTPError as e:
                logger.warning("ステータス取得失敗、再試行", attempts=attempts, error=str(e))
                continue

            status_data = data.get("data", {})
            status = status_data.get("status", "")
            logger.debug("ポーリング", attempt=attempts, status=status)

            if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
                video_id = status_data.get("publicaly_available_post_id") or [""]
                if isinstance(video_id, list) and video_id:
                    video_id = video_id[0]
                tiktok_url = (
                    f"https://www.tiktok.com/@{self.settings.tiktok_open_id}/video/{video_id}"
                    if video_id
                    else ""
                )
                return PublishResult(
                    success=True,
                    publish_id=publish_id,
                    tiktok_video_id=str(video_id),
                    tiktok_url=tiktok_url,
                    posted_at=datetime.now(),
                )
            elif status == "FAILED":
                fail_reason = status_data.get("fail_reason", "unknown")
                raise TikTokPublishError(f"投稿失敗: {fail_reason}")
            # PROCESSING_UPLOAD / PROCESSING_DOWNLOAD / PROCESSING_TRANSCODE などは継続

    def _dry_run_publish(self, plan: ContentPlan, product: Product) -> PublishResult:
        caption = self.build_caption(plan, product)
        logger.info(
            "DRY_RUN: TikTok 投稿シミュレーション",
            product=product.display_title,
            caption=caption[:80],
        )
        return PublishResult(
            success=True,
            publish_id=f"dry_run_publish_{int(asyncio.get_event_loop().time())}",
            tiktok_video_id="dry_run_video_id",
            tiktok_url="https://www.tiktok.com/dry_run",
            posted_at=datetime.now(),
        )

    async def publish_local_file(
        self,
        local_path: Path,
        plan: ContentPlan,
        product: Product,
        upload_callback: callable | None = None,  # type: ignore[type-arg]
    ) -> PublishResult:
        """ローカルファイルからアップロード → 投稿

        upload_callback: Path -> dict (gs_uri, signed_url)
        """
        if not local_path.exists():
            raise TikTokPublishError(f"動画ファイルなし: {local_path}")

        if upload_callback is None:
            raise TikTokPublishError("upload_callback が必要です")

        upload_result = await upload_callback(local_path)
        video_url = upload_result.get("signed_url") or upload_result.get("gs_uri", "")
        if not video_url:
            raise TikTokPublishError("アップロード後の URL が空")

        return await self.publish_from_url(video_url, plan, product)


def validate_caption(caption: str) -> tuple[bool, list[str]]:
    """キャプションの簡易バリデーション(ステマ規制チェック等)

    Returns:
        (有効か, 警告リスト)
    """
    warnings: list[str] = []
    has_pr = "#PR" in caption or "#pr" in caption
    has_ad = "#広告" in caption
    if not has_pr:
        warnings.append("#PR が含まれていません(ステマ規制対応必須)")
    if not has_ad:
        warnings.append("#広告 が含まれていません(ステマ規制対応必須)")
    if len(caption) > MAX_CAPTION_LENGTH:
        warnings.append(f"キャプションが長すぎます ({len(caption)} > {MAX_CAPTION_LENGTH})")
    if re.search(r"(100%|絶対|必ず効く|業界No\.?1)", caption):
        warnings.append("誇大広告に該当する可能性のある語句が含まれます")
    return (len(warnings) == 0, warnings)
