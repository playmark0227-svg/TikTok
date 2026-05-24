"""エラー通知ユーティリティ

致命的エラーは Discord に通知し、Firestore にも記録する。
Phase 5 で Discord Bot 実装後に差し替える前提のスタブ。
"""

from __future__ import annotations

from src.utils.logger import get_logger

logger = get_logger(__name__)


async def notify_error(message: str, *, exc: Exception | None = None) -> None:
    """エラーを通知する。

    Phase 0 ではログ出力のみ。Phase 5 で Discord 通知を追加。
    """
    if exc is not None:
        logger.error("エラー発生", message=message, exc_info=exc)
    else:
        logger.error("エラー発生", message=message)


async def notify_info(message: str) -> None:
    """情報通知。Phase 5 で Discord 通知を追加。"""
    logger.info("通知", message=message)
