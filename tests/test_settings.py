"""設定モジュールの単体テスト"""

from __future__ import annotations

import pytest

from config.settings import Settings, get_settings


@pytest.mark.unit
def test_settings_loads_defaults():
    """環境変数未設定でもデフォルト値で初期化できる"""
    settings = Settings(_env_file=None)
    assert settings.claude_model == "claude-opus-4-7"
    assert settings.veo_model == "veo-3.1-fast-generate-preview"
    assert settings.timezone == "Asia/Tokyo"
    assert settings.max_revision_count == 3
    assert settings.video_duration_seconds == 16


@pytest.mark.unit
def test_settings_category_list_parses():
    """カンマ区切りのカテゴリを list に変換できる"""
    settings = Settings(
        _env_file=None,
        target_categories="家電,コスメ, キッチン ,健康",
    )
    assert settings.category_list == ["家電", "コスメ", "キッチン", "健康"]


@pytest.mark.unit
def test_settings_dry_run_default_true():
    """デフォルトで DRY_RUN は True"""
    settings = Settings(_env_file=None)
    assert settings.dry_run is True
    assert settings.skip_tiktok_post is True


@pytest.mark.unit
def test_settings_validate_required_returns_missing():
    """必須キーが空ならその名前を返す"""
    settings = Settings(_env_file=None)
    missing = settings.validate_required(["anthropic_api_key", "claude_model"])
    assert "anthropic_api_key" in missing
    assert "claude_model" not in missing


@pytest.mark.unit
def test_get_settings_is_cached():
    """get_settings は同じインスタンスを返す"""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
