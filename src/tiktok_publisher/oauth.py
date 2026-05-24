"""TikTok OAuth トークン管理

アクセストークンは 24時間で期限切れ、リフレッシュトークンで自動更新する。
トークンは Firestore の tokens コレクションに保存。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from src.database.firestore_client import FirestoreClient
from src.database.models import TokenRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)

TOKEN_ENDPOINT = "https://open.tiktokapis.com/v2/oauth/token/"
AUTH_ENDPOINT = "https://www.tiktok.com/v2/auth/authorize/"
REVOKE_ENDPOINT = "https://open.tiktokapis.com/v2/oauth/revoke/"
REQUEST_TIMEOUT = 15.0
EARLY_REFRESH_BUFFER = timedelta(hours=1)

OAUTH_SCOPES = [
    "user.info.basic",
    "video.publish",
    "video.upload",
]


class TikTokOAuthError(Exception):
    """TikTok OAuth エラー"""


class TikTokOAuthManager:
    """TikTok OAuth トークン管理"""

    def __init__(
        self,
        settings: Settings | None = None,
        firestore_client: FirestoreClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.firestore = firestore_client or FirestoreClient(self.settings)

    def build_authorize_url(self, state: str = "csrf-token") -> str:
        """OAuth 認可 URL を生成(初回認証用)"""
        params = {
            "client_key": self.settings.tiktok_client_key,
            "scope": ",".join(OAUTH_SCOPES),
            "response_type": "code",
            "redirect_uri": self.settings.tiktok_redirect_uri,
            "state": state,
        }
        return f"{AUTH_ENDPOINT}?" + "&".join(f"{k}={v}" for k, v in params.items())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((TikTokOAuthError, httpx.HTTPError)),
        reraise=True,
    )
    async def exchange_code(self, code: str) -> TokenRecord:
        """認可コードをアクセストークンに交換"""
        if self.settings.is_dry_run:
            return self._dry_run_token()

        if not self.settings.tiktok_client_key or not self.settings.tiktok_client_secret:
            raise TikTokOAuthError("TikTok クライアント情報が未設定")

        data = {
            "client_key": self.settings.tiktok_client_key,
            "client_secret": self.settings.tiktok_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.settings.tiktok_redirect_uri,
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        token = self._parse_token_response(response)
        await self.firestore.save_token(token)
        return token

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((TikTokOAuthError, httpx.HTTPError)),
        reraise=True,
    )
    async def refresh(self, refresh_token: str) -> TokenRecord:
        """リフレッシュトークンで更新"""
        if self.settings.is_dry_run:
            return self._dry_run_token()

        data = {
            "client_key": self.settings.tiktok_client_key,
            "client_secret": self.settings.tiktok_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        token = self._parse_token_response(response)
        await self.firestore.save_token(token)
        return token

    async def get_valid_access_token(self) -> str:
        """有効なアクセストークンを取得(必要なら自動更新)"""
        if self.settings.is_dry_run:
            return "dry_run_access_token"

        record = await self.firestore.get_token("tiktok")
        if record is None:
            # .env のフォールバック値を試す
            if self.settings.tiktok_access_token:
                logger.info("Firestore にトークンなし、.env を使用")
                return self.settings.tiktok_access_token
            raise TikTokOAuthError(
                "TikTok トークン未保存。scripts/tiktok_oauth_init.py を実行してください"
            )

        if datetime.now() >= record.expires_at - EARLY_REFRESH_BUFFER:
            logger.info("アクセストークン期限間近、更新")
            record = await self.refresh(record.refresh_token)

        return record.access_token

    def _parse_token_response(self, response: httpx.Response) -> TokenRecord:
        try:
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error("TikTok トークン取得HTTPエラー", body=response.text)
            raise TikTokOAuthError(f"トークン取得失敗: {response.status_code}") from e

        if "error" in data and data.get("error") and data.get("error") != "":
            raise TikTokOAuthError(f"TikTok エラー: {data.get('error_description', data.get('error'))}")

        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = int(data.get("expires_in", 86400))
        if not access_token or not refresh_token:
            raise TikTokOAuthError(f"トークンフィールド不足: {data}")

        return TokenRecord(
            service="tiktok",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.now() + timedelta(seconds=expires_in),
            updated_at=datetime.now(),
        )

    def _dry_run_token(self) -> TokenRecord:
        return TokenRecord(
            service="tiktok",
            access_token="dry_run_access_token",
            refresh_token="dry_run_refresh_token",
            expires_at=datetime.now() + timedelta(hours=24),
            updated_at=datetime.now(),
        )
