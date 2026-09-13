from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
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


async def compute_consumption(session: AsyncSession, project_id: uuid.UUID | None) -> int:
    """Sum of size_bytes for every non-deleted transfer in the quota bucket -
    project-scoped, or the shared unscoped bucket when project_id is None."""
    stmt = select(func.coalesce(func.sum(TransferModel.size_bytes), 0)).where(
        TransferModel.status != "deleted"
    )
    stmt = stmt.where(TransferModel.project_id == project_id)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def _lock_quota_bucket(session: AsyncSession, project_id: uuid.UUID | None) -> None:
    """Postgres advisory lock scoped to the current transaction: held until
    this session's commit/rollback, so a concurrent request for the same
    bucket blocks here instead of both readers seeing the same stale
    consumption and both passing the check (same race class as DEC-0015)."""
    bucket_key = str(project_id) if project_id else "unscoped-transfer-quota"
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": bucket_key})


async def _enforce_transfer_limits(
    session: AsyncSession, settings: Settings, project_id: uuid.UUID | None, size_bytes: int
) -> None:
    if size_bytes > settings.transfer_max_size_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error_code": "transfer_too_large",
                "size_bytes": size_bytes,
                "max_size_bytes": settings.transfer_max_size_bytes,
            },
        )
    await _lock_quota_bucket(session, project_id)
    consumed = await compute_consumption(session, project_id)
    if consumed + size_bytes > settings.transfer_project_quota_bytes:
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE,
            detail={
                "error_code": "quota_exceeded",
                "project_id": str(project_id) if project_id else None,
                "consumed_bytes": consumed,
                "requested_bytes": size_bytes,
                "quota_bytes": settings.transfer_project_quota_bytes,
            },
        )


async def create_transfer(
    session: AsyncSession,
    settings: Settings,
    transfer_in: TransferCreate,
    sender_user_id: uuid.UUID,
    project_slug: str,
) -> TransferModel:
    await _enforce_transfer_limits(
        session, settings, transfer_in.project_id, transfer_in.size_bytes
    )
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


def initiate_upload(
    storage: StorageProvider, settings: Settings, transfer: TransferModel
) -> UploadInitiateResponse:
    if transfer.size_bytes <= MULTIPART_THRESHOLD_BYTES:
        url = storage.presign_put(transfer.object_key, transfer.content_type)
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
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "missing_upload_id"},
            )
        storage.complete_multipart_upload(transfer.object_key, upload_id=upload_id, parts=parts)
    head = storage.head_object(transfer.object_key)
    actual_size = head.get("ContentLength")
    if actual_size is not None and actual_size != size_bytes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error_code": "size_mismatch", "expected": size_bytes, "actual": actual_size},
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


async def expire_transfers(session: AsyncSession, storage: StorageProvider) -> list[TransferModel]:
    """Retention worker (roadmap etape 4.3, DEC-0020): deletes every transfer
    whose `expires_at` has passed and that isn't already deleted, both the
    MinIO object and the DB row. Committing one transfer at a time keeps a
    failure on one object from losing progress already made on the others,
    and re-running this against the same expired set is a no-op since the
    `status != "deleted"` filter excludes rows a previous run already
    cleared."""
    stmt = select(TransferModel).where(
        TransferModel.expires_at.is_not(None),
        TransferModel.expires_at <= datetime.now(UTC),
        TransferModel.status != "deleted",
    )
    result = await session.execute(stmt)
    expired = list(result.scalars().all())
    for transfer in expired:
        await delete_transfer(session, storage, transfer)
    return expired
