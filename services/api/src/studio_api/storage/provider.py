from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import cast

import boto3  # type: ignore[import-untyped]

from studio_api.settings import Settings

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
    process (.claude/rules/storage-transfers.md golden rule)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._signing_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_public_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        self._admin_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    def presign_put(self, object_key: str, content_type: str) -> str:
        return cast(
            str,
            self._signing_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._settings.s3_bucket,
                    "Key": object_key,
                    "ContentType": content_type,
                },
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

    def create_multipart_upload(self, object_key: str, content_type: str) -> str:
        response = self._admin_client.create_multipart_upload(
            Bucket=self._settings.s3_bucket, Key=object_key, ContentType=content_type
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

    def complete_multipart_upload(
        self, object_key: str, upload_id: str, parts: dict[int, str]
    ) -> None:
        self._admin_client.complete_multipart_upload(
            Bucket=self._settings.s3_bucket,
            Key=object_key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": number, "ETag": etag} for number, etag in sorted(parts.items())
                ]
            },
        )

    def head_object(self, object_key: str) -> dict[str, object]:
        return cast(
            dict[str, object],
            self._admin_client.head_object(Bucket=self._settings.s3_bucket, Key=object_key),
        )

    def delete_object(self, object_key: str) -> None:
        self._admin_client.delete_object(Bucket=self._settings.s3_bucket, Key=object_key)
