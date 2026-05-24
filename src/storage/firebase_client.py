"""Firebase Storage クライアント

編集済み動画をアップロードし、ダウンロード可能な署名付き URL を返す。
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StorageError(Exception):
    """Storage 操作エラー"""


class FirebaseStorageClient:
    """Firebase Cloud Storage クライアント

    DRY_RUN モードではローカルに保存し、file:// URL を返す。
    """

    def __init__(self, settings: Settings | None = None, bucket: Any = None):
        self.settings = settings or get_settings()
        self._bucket = bucket

    def _get_bucket(self) -> Any:
        if self._bucket is not None:
            return self._bucket

        if self.settings.is_dry_run:
            logger.info("DRY_RUN: Firebase Storage 初期化スキップ")
            self._bucket = "dry_run_bucket"
            return self._bucket

        try:
            import firebase_admin
            from firebase_admin import credentials, storage
        except ImportError as e:
            raise StorageError("firebase-admin がインストールされていません") from e

        if not firebase_admin._apps:
            cred_path = self.settings.firebase_credentials_full_path
            if not cred_path.exists():
                raise StorageError(f"Firebase 認証情報なし: {cred_path}")
            cred = credentials.Certificate(str(cred_path))
            firebase_admin.initialize_app(
                cred,
                {
                    "projectId": self.settings.firebase_project_id,
                    "storageBucket": self.settings.firebase_storage_bucket,
                },
            )

        bucket_name = self.settings.firebase_storage_bucket
        self._bucket = storage.bucket(bucket_name) if bucket_name else storage.bucket()
        return self._bucket

    async def upload_video(
        self,
        local_path: Path,
        *,
        remote_name: str | None = None,
        content_type: str = "video/mp4",
        signed_url_expiration_days: int = 7,
    ) -> dict[str, str]:
        """動画をアップロード

        Returns:
            {"gs_uri": "gs://...", "signed_url": "https://..."}
        """
        if not local_path.exists():
            raise StorageError(f"アップロード対象ファイルなし: {local_path}")

        remote_name = remote_name or f"videos/{uuid.uuid4().hex}.mp4"
        logger.info(
            "Storage: アップロード開始",
            local=str(local_path),
            remote=remote_name,
            size=local_path.stat().st_size,
        )

        if self.settings.is_dry_run:
            return self._dry_run_upload(local_path, remote_name)

        bucket = self._get_bucket()
        loop = asyncio.get_event_loop()

        def _do_upload() -> dict[str, str]:
            blob = bucket.blob(remote_name)
            blob.upload_from_filename(str(local_path), content_type=content_type)
            signed_url = blob.generate_signed_url(
                expiration=timedelta(days=signed_url_expiration_days),
                method="GET",
            )
            return {
                "gs_uri": f"gs://{bucket.name}/{remote_name}",
                "signed_url": signed_url,
                "blob_name": remote_name,
            }

        try:
            result = await loop.run_in_executor(None, _do_upload)
            logger.info("Storage: アップロード完了", gs_uri=result["gs_uri"])
            return result
        except Exception as e:
            logger.error("Storage: アップロード失敗", error=str(e))
            raise StorageError(f"アップロード失敗: {e}") from e

    def _dry_run_upload(self, local_path: Path, remote_name: str) -> dict[str, str]:
        """DRY_RUN: ローカルにコピーして file:// URL を返す"""
        dry_dir = self.settings.storage_local_dir / "dry_run_uploads"
        dry_dir.mkdir(parents=True, exist_ok=True)
        dest = dry_dir / Path(remote_name).name
        shutil.copyfile(local_path, dest)
        url = f"file://{dest.resolve()}"
        return {
            "gs_uri": f"gs://dry-run-bucket/{remote_name}",
            "signed_url": url,
            "blob_name": remote_name,
        }

    async def delete_blob(self, blob_name: str) -> None:
        if self.settings.is_dry_run:
            logger.info("DRY_RUN: delete スキップ", blob=blob_name)
            return
        bucket = self._get_bucket()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: bucket.blob(blob_name).delete())
