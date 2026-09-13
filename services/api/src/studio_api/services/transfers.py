from __future__ import annotations

import base64
import binascii
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.transfers import TransferCategory, TransferCreate, UploadInitiateResponse

from studio_api.db.models.transfer import TransferModel
from studio_api.settings import Settings
from studio_api.storage.provider import StorageProvider, safe_object_key

MULTIPART_THRESHOLD_BYTES = 128 * 1024 * 1024
PART_SIZE_BYTES = 64 * 1024 * 1024

_RETENTION_DAYS = {
    TransferCategory.TEMPORARY: 7,
    TransferCategory.BUILD: 30,
}


def _generate_transfer_code() -> str:
    return f"TRF-{secrets.token_hex(4).upper()}"


async def create_transfer(
    session: AsyncSession, transfer_in: TransferCreate, sender_user_id: uuid.UUID, project_slug: str
) -> TransferModel:
    transfer_id = uuid.uuid4()
    now = datetime.now(UTC)
    retention_days = _RETENTION_DAYS.get(transfer_in.category)
    transfer = TransferModel(
        id=transfer_id,
        transfer_code=_generate_transfer_code(),
        sender_user_id=sender_user_id,
        recipient_user_id=transfer_in.recipient_user_id,
        project_id=transfer_in.project_id,
        task_id=transfer_in.task_id,
        category=transfer_in.category.value,
        filename=transfer_in.filename,
        object_key=safe_object_key(project_slug, transfer_id, transfer_in.filename),
        content_type=transfer_in.content_type,
        size_bytes=transfer_in.size_bytes,
        status="created",
        expires_at=(now + timedelta(days=retention_days)) if retention_days else None,
        created_at=now,
    )
    session.add(transfer)
    await session.commit()
    await session.refresh(transfer)
    return transfer


async def get_transfer(session: AsyncSession, transfer_id: uuid.UUID) -> TransferModel:
    transfer = await session.get(TransferModel, transfer_id)
    if transfer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "transfer not found")
    return transfer


async def list_transfers(
    session: AsyncSession, project_id: uuid.UUID | None = None
) -> list[TransferModel]:
    stmt = select(TransferModel)
    if project_id is not None:
        stmt = stmt.where(TransferModel.project_id == project_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def initiate_upload(
    session: AsyncSession,
    storage: StorageProvider,
    settings: Settings,
    transfer: TransferModel,
    content_md5: str | None,
) -> UploadInitiateResponse:
    if transfer.size_bytes <= MULTIPART_THRESHOLD_BYTES:
        if not content_md5:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error_code": "missing_content_md5"},
            )
        url = storage.presign_put(transfer.object_key, transfer.content_type, content_md5)
        transfer.content_md5 = content_md5
        await session.commit()
        return UploadInitiateResponse(transfer_id=transfer.id, multipart=False, upload_url=url)

    upload_id = storage.create_multipart_upload(transfer.object_key, transfer.content_type)
    part_count = (transfer.size_bytes + PART_SIZE_BYTES - 1) // PART_SIZE_BYTES
    part_urls = {
        n: storage.presign_upload_part(transfer.object_key, upload_id, n)
        for n in range(1, part_count + 1)
    }
    return UploadInitiateResponse(
        transfer_id=transfer.id,
        multipart=True,
        upload_id=upload_id,
        part_urls=part_urls,
        part_size_bytes=PART_SIZE_BYTES,
    )


async def complete_upload(
    session: AsyncSession,
    storage: StorageProvider,
    transfer: TransferModel,
    size_bytes: int,
    sha256: str,
    upload_id: str | None,
    parts: dict[int, str] | None,
) -> TransferModel:
    if parts:
        if not upload_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error_code": "missing_upload_id"},
            )
        storage.complete_multipart_upload(transfer.object_key, upload_id=upload_id, parts=parts)
    try:
        head = storage.head_object(transfer.object_key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "404":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error_code": "object_not_found"},
            ) from exc
        raise
    actual_size = head.get("ContentLength")
    if actual_size is not None and actual_size != size_bytes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "size_mismatch", "expected": size_bytes, "actual": actual_size},
        )
    if not parts and transfer.content_md5:
        # Single-PUT path: MinIO/S3 already refused any byte mismatch against
        # the presigned Content-MD5 (DEC-0014). This re-check is defense in
        # depth against a storage backend that enforces it less strictly.
        actual_etag = str(head.get("ETag", "")).strip('"')
        try:
            expected_hex = base64.b64decode(transfer.content_md5).hex()
        except binascii.Error:
            expected_hex = ""
        if expected_hex != actual_etag:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error_code": "content_md5_mismatch"},
            )
    transfer.size_bytes = size_bytes
    transfer.sha256 = sha256
    transfer.status = "ready"
    transfer.uploaded_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(transfer)
    return transfer


def get_download_url(
    storage: StorageProvider, settings: Settings, transfer: TransferModel
) -> tuple[str, datetime]:
    url = storage.presign_get(transfer.object_key)
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.presigned_url_ttl_seconds)
    return url, expires_at


async def mark_downloaded(session: AsyncSession, transfer: TransferModel) -> TransferModel:
    transfer.downloaded_at = datetime.now(UTC)
    transfer.status = "downloaded"
    await session.commit()
    await session.refresh(transfer)
    return transfer


async def delete_transfer(
    session: AsyncSession, storage: StorageProvider, transfer: TransferModel
) -> None:
    """Never delete a non-expired transfer without an explicit policy behind it
    (AI/01_AI_OPERATING_REFERENCE.md) — this path is for an explicit user/API
    delete request, not automatic cleanup."""
    storage.delete_object(transfer.object_key)
    transfer.status = "deleted"
    transfer.deleted_at = datetime.now(UTC)
    await session.commit()
