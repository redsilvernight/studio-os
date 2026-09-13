from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate


class TransferStatus(StrEnum):
    """Mirrors transfer.* event types in TECH/03_EVENT_CONTRACT.md."""

    CREATED = "created"
    UPLOADING = "uploading"
    READY = "ready"
    DOWNLOADED = "downloaded"
    EXPIRED = "expired"
    DELETED = "deleted"


class TransferCategory(StrEnum):
    """Retention classes named in .claude/rules/storage-transfers.md: temporary
    transfer 7d, build 30d, asset manual/long, raw recording local-only."""

    TEMPORARY = "temporary"
    BUILD = "build"
    ASSET = "asset"
    RAW_RECORDING = "raw_recording"


class Transfer(ContractModel):
    """Fields per .claude/rules/database.md / TECH/05_DATA_MODEL.md — no field
    beyond this list without a contract change."""

    id: UUID
    transfer_code: str
    sender_user_id: UUID
    recipient_user_id: UUID | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None
    category: TransferCategory
    filename: str
    object_key: str
    content_type: str
    size_bytes: int
    sha256: str | None = None
    content_md5: str | None = None
    status: TransferStatus = TransferStatus.CREATED
    expires_at: datetime | None = None
    created_at: datetime
    uploaded_at: datetime | None = None
    downloaded_at: datetime | None = None
    deleted_at: datetime | None = None


class TransferCreate(IdempotentCreate):
    recipient_user_id: UUID | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None
    category: TransferCategory
    filename: str
    content_type: str
    size_bytes: int


class UploadInitiateRequest(ContractModel):
    """`content_md5` (RFC 1864, base64-encoded MD5 of the whole file) is
    required for the single-PUT path: the server presigns the PUT with it, so
    MinIO/S3 itself rejects any byte mismatch at upload time with `BadDigest`
    (DEC-0014) — no bytes ever flow through the API process. Not used for the
    multipart path (see DEC-0014 for why a whole-object checksum can't be
    enforced the same way there)."""

    content_md5: str | None = None


class UploadInitiateResponse(ContractModel):
    """Small file: a single pre-signed PUT. Large file: multipart parts, each
    with its own pre-signed URL — see TECH/06_STORAGE_TRANSFER_SPEC.md."""

    transfer_id: UUID
    multipart: bool
    upload_url: str | None = None
    upload_id: str | None = None
    part_urls: dict[int, str] | None = None
    part_size_bytes: int | None = None


class UploadCompleteRequest(ContractModel):
    """Multipart parts/upload_id are tracked client-side per
    .claude/rules/storage-transfers.md and handed back here — the server never
    persists multipart-in-progress state.

    `sha256` is recorded as reported by the client. For the single-PUT path it
    is corroborated by the server-verified `content_md5` (DEC-0014); for
    multipart it remains an unverified client claim — MinIO/S3 offer no native
    whole-object checksum over presigned URLs (DEC-0014)."""

    size_bytes: int
    sha256: str
    upload_id: str | None = None
    parts: dict[int, str] | None = None  # part number -> ETag, multipart only


class DownloadUrlResponse(ContractModel):
    transfer_id: UUID
    download_url: str
    expires_at: datetime
