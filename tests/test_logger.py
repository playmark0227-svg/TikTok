"""ロガー設定の単体テスト"""

from __future__ import annotations

import logging

import pytest

from src.utils.logger import configure_logging, get_logger


@pytest.mark.unit
def test_get_logger_returns_bound_logger():
    """get_logger が BoundLogger を返す"""
    logger = get_logger("test")
    assert logger is not None
    # 基本的なメソッドが呼べる
    logger.info("テストメッセージ")


@pytest.mark.unit
def test_configure_logging_sets_handlers(tmp_path, monkeypatch):
    """configure_logging で root logger にハンドラが設定される"""
    monkeypatch.setattr("src.utils.logger.LOG_DIR", tmp_path)
    monkeypatch.setattr("src.utils.logger.LOG_FILE", tmp_path / "test.log")

    configure_logging()

    root_logger = logging.getLogger()
    assert len(root_logger.handlers) >= 2  # stream + file


@pytest.mark.unit
def test_logger_can_log_japanese():
    """日本語ログを出力できる"""
    logger = get_logger("test.japanese")
    logger.info("日本語テスト", category="家電", price=1000)
