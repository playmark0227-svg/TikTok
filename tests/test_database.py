"""Firestore + Storage モジュールの単体テスト"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from config.settings import Settings
from src.database.firestore_client import FirestoreClient
from src.database.models import (
    AnalyticsSnapshot,
    PostRecord,
    ProductRecord,
    TokenRecord,
)
from src.storage.firebase_client import FirebaseStorageClient, StorageError
from src.storage.local_cache import LocalCache


@pytest.mark.unit
class TestModels:
    def test_product_record_to_firestore(self):
        rec = ProductRecord(
            product_id="P1",
            source="amazon",
            title="Test",
            selected_at=datetime.now(),
        )
        d = rec.to_firestore()
        assert d["product_id"] == "P1"

    def test_post_record_default_status(self):
        rec = PostRecord(
            post_id="POST1",
            product_id="P1",
            veo_prompt="prompt",
            caption="cap",
            hashtags=["#PR"],
        )
        assert rec.status == "draft"
        assert rec.revision_count == 0

    def test_analytics_snapshot_defaults(self):
        a = AnalyticsSnapshot()
        assert a.views == 0
        assert a.likes == 0


# ----- Firestore DRY_RUN Tests -----


@pytest.mark.unit
class TestFirestoreDryRun:
    @pytest.mark.asyncio
    async def test_save_and_get_product(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = FirestoreClient(settings)
        record = ProductRecord(
            product_id="P1",
            source="amazon",
            title="Test",
            selected_at=datetime.now(),
        )
        await client.save_product(record)
        data = await client._get("products", "P1")
        assert data is not None
        assert data["product_id"] == "P1"

    @pytest.mark.asyncio
    async def test_save_and_get_post(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = FirestoreClient(settings)
        record = PostRecord(
            post_id="POST1",
            product_id="P1",
            veo_prompt="prompt",
            caption="cap",
            hashtags=["#PR"],
        )
        await client.save_post(record)
        data = await client._get("posts", "POST1")
        assert data is not None
        assert data["status"] == "draft"

    @pytest.mark.asyncio
    async def test_update_post_status(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = FirestoreClient(settings)
        record = PostRecord(
            post_id="POST1",
            product_id="P1",
            veo_prompt="prompt",
            caption="cap",
            hashtags=["#PR"],
        )
        await client.save_post(record)
        await client.update_post_status("POST1", "posted", tiktok_video_id="V123")
        data = await client._get("posts", "POST1")
        assert data["status"] == "posted"
        assert data["tiktok_video_id"] == "V123"

    @pytest.mark.asyncio
    async def test_save_and_get_token(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = FirestoreClient(settings)
        record = TokenRecord(
            service="tiktok",
            access_token="atoken",
            refresh_token="rtoken",
            expires_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await client.save_token(record)
        fetched = await client.get_token("tiktok")
        assert fetched is not None
        assert fetched.access_token == "atoken"

    @pytest.mark.asyncio
    async def test_daily_stats_increment(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = FirestoreClient(settings)
        await client.increment_daily_posts("2026-05-24")
        await client.increment_daily_posts("2026-05-24")
        stats = await client.get_daily_stats("2026-05-24")
        assert stats.posts_count == 2

    @pytest.mark.asyncio
    async def test_query_filter_works(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = FirestoreClient(settings)
        # 直接 store に投入
        await client._set("posts", "P1", {"status": "posted", "post_id": "P1"})
        await client._set("posts", "P2", {"status": "draft", "post_id": "P2"})
        results = await client._query(
            "posts",
            where=[("status", "==", "posted")],
        )
        assert len(results) == 1
        assert results[0]["post_id"] == "P1"


# ----- Storage DRY_RUN Tests -----


@pytest.mark.unit
class TestStorageDryRun:
    @pytest.mark.asyncio
    async def test_upload_creates_local_copy(self, tmp_path: Path):
        settings = Settings(_env_file=None, dry_run=True)
        settings.storage_local_dir.mkdir(parents=True, exist_ok=True)
        client = FirebaseStorageClient(settings)

        src = tmp_path / "test.mp4"
        src.write_bytes(b"fake mp4 content")

        result = await client.upload_video(src, remote_name="videos/test.mp4")
        assert result["signed_url"].startswith("file://")
        assert result["gs_uri"].startswith("gs://")

    @pytest.mark.asyncio
    async def test_upload_missing_file_raises(self):
        settings = Settings(_env_file=None, dry_run=True)
        client = FirebaseStorageClient(settings)
        with pytest.raises(StorageError):
            await client.upload_video(Path("/nonexistent.mp4"))


# ----- LocalCache Tests -----


@pytest.mark.unit
class TestLocalCache:
    def test_get_size_returns_float(self):
        settings = Settings(_env_file=None, dry_run=True)
        cache = LocalCache(settings)
        size = cache.get_size_mb()
        assert isinstance(size, float)
        assert size >= 0

    def test_cleanup_old_files_returns_int(self):
        settings = Settings(_env_file=None, dry_run=True)
        cache = LocalCache(settings)
        deleted = cache.cleanup_old_files(retention_days=100)
        assert isinstance(deleted, int)
