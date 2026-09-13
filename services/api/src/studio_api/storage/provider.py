from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import cast

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from studio_api.settings import Settings, get_settings

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_object_key(project_slug: str, transfer_id: uuid.UUID, filename: str) -> str:
    """Never trust a client filename inside the storage key
    (.claude/rules/storage-transfers.md).
    Layout: studio/{project}/{yyyy}/{mm}/{transfer_uuid}/{safe_name}."""
    now = datetime.now(UTC)
    safe_name = _UNSAFE_CHARS.sub("_", filename)[:200]
    return f"studio/{project_slug}/{now:%Y}/{now:%m}/{transfer_id}/{safe_name}"


class StorageProvider:
    """S3-compatible (MinIO) presigning only — bytes never flow through this
    process (.claude/rules/storage-transfers.md golden rule).

    Presigning methods (`presign_*`) are pure local signature computation, no
    network I/O, and stay synchronous. Methods that make a real network call
    to the storage backend (`create_multipart_upload`, `complete_multipart_upload`,
    `head_object`, `delete_object`) are `async def`, offloading the blocking
    boto3 call to a worker thread (`asyncio.to_thread`) so they never block the
    FastAPI event loop (.claude/rules/python-conventions.md) — DEC-0026."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Force SigV4: boto3 falls back to legacy SigV2 for a non-AWS endpoint
        # unless told otherwise, and SigV2 rejects any header (e.g.
        # Content-MD5) that wasn't part of its signed set — breaking the
        # native checksum enforcement DEC-0025 relies on. Real AWS S3 has
        # dropped SigV2 entirely, so this also fixes portability off MinIO.
        signing_config = Config(signature_version="s3v4")
        self._signing_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_public_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=signing_config,
        )
        self._admin_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=signing_config,
        )

    def presign_put(
        self, object_key: str, content_type: str, content_md5: str | None = None
    ) -> str:
        params: dict[str, object] = {
            "Bucket": self._settings.s3_bucket,
            "Key": object_key,
            "ContentType": content_type,
        }
        if content_md5 is not None:
            params["ContentMD5"] = content_md5
        return cast(
            str,
            self._signing_client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=self._settings.presigned_url_ttl_seconds,
            ),
        )

    def presign_get(self, object_key: str) -> str:
        return cast(
            str,
            self._signing_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._settings.s3_bucket, "Key": object_key},
                ExpiresIn=self._settings.presigned_url_ttl_seconds,
            ),
        )

    async def create_multipart_upload(self, object_key: str, content_type: str) -> str:
        response = await asyncio.to_thread(
            self._admin_client.create_multipart_upload,
            Bucket=self._settings.s3_bucket,
            Key=object_key,
            ContentType=content_type,
        )
        return cast(str, response["UploadId"])

    def presign_upload_part(self, object_key: str, upload_id: str, part_number: int) -> str:
        return cast(
            str,
            self._signing_client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": self._settings.s3_bucket,
                    "Key": object_key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=self._settings.presigned_url_ttl_seconds,
            ),
        )

    async def complete_multipart_upload(
        self, object_key: str, upload_id: str, parts: dict[int, str]
    ) -> None:
        await asyncio.to_thread(
            self._admin_client.complete_multipart_upload,
            Bucket=self._settings.s3_bucket,
            Key=object_key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": number, "ETag": etag} for number, etag in sorted(parts.items())
                ]
            },
        )

    async def head_object(self, object_key: str) -> dict[str, object]:
        response = await asyncio.to_thread(
            self._admin_client.head_object, Bucket=self._settings.s3_bucket, Key=object_key
        )
        return cast(dict[str, object], response)

    async def delete_object(self, object_key: str) -> None:
        await asyncio.to_thread(
            self._admin_client.delete_object, Bucket=self._settings.s3_bucket, Key=object_key
        )


@lru_cache
def get_storage() -> StorageProvider:
    """Cached factory (DEC-0026): constructing a `boto3.client()` is itself
    blocking and non-trivial (botocore service-model loading from disk), so
    building a fresh `StorageProvider` per-request would defeat the point of
    making its network calls async. Mirrors the module-level engine cache in
    `studio_api/db/session.py`."""
    return StorageProvider(get_settings())
