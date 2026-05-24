"""TikTok OAuth 初回認証スクリプト

ブラウザで TikTok 認可 URL を開き、コールバックで code を受け取って
アクセストークンに交換し、Firestore に保存する。

審査通過後に1度だけ実行する。
"""

from __future__ import annotations

import asyncio
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from src.database.firestore_client import FirestoreClient  # noqa: E402
from src.tiktok_publisher.oauth import (  # noqa: E402
    TikTokOAuthError,
    TikTokOAuthManager,
)
from src.utils.logger import configure_logging, get_logger  # noqa: E402

received_code: dict[str, str] = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        state = params.get("state", [""])[0]
        error = params.get("error", [""])[0]

        if error:
            received_code["error"] = error
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h1>認可エラー: {error}</h1>".encode())
            return

        if not code:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h1>code パラメータがありません</h1>".encode())
            return

        received_code["code"] = code
        received_code["state"] = state
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            "<h1>TikTok 認可成功</h1><p>このタブを閉じてターミナルに戻ってください。</p>".encode()
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A002, N802
        pass  # サーバログ抑制


async def main() -> int:
    configure_logging()
    logger = get_logger(__name__)
    settings = get_settings()

    if not settings.tiktok_client_key or not settings.tiktok_client_secret:
        logger.error(
            "TikTok クライアント情報が未設定。"
            ".env の TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET を設定してください"
        )
        return 1

    firestore = FirestoreClient(settings)
    oauth = TikTokOAuthManager(settings=settings, firestore_client=firestore)

    state = secrets.token_urlsafe(16)
    auth_url = oauth.build_authorize_url(state=state)

    print("\n=== TikTok OAuth 認証 ===")
    print(f"認可 URL: {auth_url}")
    print("\nコールバック待機ポート: 8080")
    print(f"redirect_uri: {settings.tiktok_redirect_uri}\n")

    # HTTP サーバを別スレッドで起動
    parsed = urlparse(settings.tiktok_redirect_uri)
    port = parsed.port or 8080
    server = HTTPServer(("0.0.0.0", port), CallbackHandler)

    def serve() -> None:
        server.handle_request()

    server_thread = Thread(target=serve, daemon=True)
    server_thread.start()

    try:
        webbrowser.open(auth_url)
    except Exception:
        print("ブラウザを自動で開けませんでした。手動で上記 URL を開いてください。")

    print("ブラウザで認可してください。コールバックを待機中...")
    # サーバスレッド完了待ち
    server_thread.join(timeout=300)

    if "error" in received_code:
        logger.error("認可エラー", error=received_code["error"])
        return 1

    if "code" not in received_code:
        logger.error("コールバックが届きませんでした(タイムアウト)")
        return 1

    if received_code.get("state") != state:
        logger.error("state 不一致(CSRF の可能性)")
        return 1

    code = received_code["code"]
    print(f"\n認可コード受信: {code[:20]}...")

    try:
        token = await oauth.exchange_code(code)
    except TikTokOAuthError as e:
        logger.error("トークン交換失敗", error=str(e))
        return 1

    print("\n✓ アクセストークン取得・Firestore 保存完了")
    print(f"  expires_at: {token.expires_at.isoformat()}")
    print(f"  refresh_token: {token.refresh_token[:20]}...")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
