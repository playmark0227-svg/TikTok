"""pytest 共通フィクスチャ"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# テスト時はデフォルトで DRY_RUN モードにする
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("SKIP_TIKTOK_POST", "true")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture(scope="session")
def project_root() -> Path:
    """プロジェクトルートディレクトリ"""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def tmp_storage_dir(tmp_path: Path) -> Path:
    """一時的なストレージディレクトリ"""
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "generated").mkdir()
    (storage / "edited").mkdir()
    (storage / "temp").mkdir()
    return storage
