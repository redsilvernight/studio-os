from __future__ import annotations

import base64
import binascii
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.transfers import (
    TransferCategory,
    TransferCreate,
    UploadInitiateResponse,
    UploadPartsRefreshResponse,
)

from studio_api.db.models.transfer import TransferModel
from studio_api.services.authz import Principal, ensure_can_write, ensure_transfer_access
from studio_api.services.authz import transfer_visibility_clause as _visibility_clause
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
    principal: Principal,
    settings: Settings,
    transfer_in: TransferCreate,
    project_slug: str,
) -> TransferModel:
    ensure_can_write(principal, "transfer")
    await _enforce_transfer_limits(
        session, settings, transfer_in.project_id, transfer_in.size_bytes
    )
    transfer_id = uuid.uuid4()
    now = datetime.now(UTC)
    retention_days = _RETENTION_DAYS.get(transfer_in.category)
    transfer = TransferModel(
        id=transfer_id,
        transfer_code=_generate_transfer_code(),
        sender_user_id=principal.user.id,
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


async def get_transfer(
    session: AsyncSession, principal: Principal, transfer_id: uuid.UUID
) -> TransferModel:
    transfer = await session.get(TransferModel, transfer_id)
    if transfer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "transfer not found")
    ensure_transfer_access(principal, transfer, "read")
    return transfer


async def list_transfers(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID | None = None
) -> list[TransferModel]:
    stmt = select(TransferModel)
    if project_id is not None:
        stmt = stmt.where(TransferModel.project_id == project_id)
    visibility = _visibility_clause(principal)
    if visibility is not None:
        stmt = stmt.where(visibility)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def initiate_upload(
    session: AsyncSession,
    principal: Principal,
    storage: StorageProvider,
    settings: Settings,
    transfer: TransferModel,
    content_md5: str | None,
) -> UploadInitiateResponse:
    ensure_transfer_access(principal, transfer, "write")
    if transfer.status == "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "transfer_already_ready"},
        )
    if transfer.size_bytes <= MULTIPART_THRESHOLD_BYTES:
        if not content_md5:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "missing_content_md5"},
            )
        url = storage.presign_put(transfer.object_key, transfer.content_type, content_md5)
        transfer.content_md5 = content_md5
        await session.commit()
        return UploadInitiateResponse(transfer_id=transfer.id, multipart=False, upload_url=url)

    upload_id = await storage.create_multipart_upload(transfer.object_key, transfer.content_type)
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
        part_urls_expires_at=datetime.now(UTC)
        + timedelta(seconds=settings.presigned_url_ttl_seconds),
    )


async def refresh_upload_parts(
    session: AsyncSession,
    principal: Principal,
    storage: StorageProvider,
    settings: Settings,
    transfer: TransferModel,
    upload_id: str,
    part_size_bytes: int | None,
    part_numbers: list[int] | None,
) -> UploadPartsRefreshResponse:
    """Re-presigns only the parts of `upload_id` that storage has not yet
    durably accepted (DEC-0037) — lets a multipart upload resume after its
    original per-part URLs expired, without ever re-uploading a part already
    confirmed by `ListParts` (the authoritative source, not a server-side
    table: this server deliberately never persists in-progress multipart
    state, TECH/06_STORAGE_TRANSFER_SPEC.md)."""
    ensure_transfer_access(principal, transfer, "write")
    if transfer.status == "ready":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "transfer_already_ready"},
        )
    if part_size_bytes is not None and part_size_bytes != PART_SIZE_BYTES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "part_size_mismatch",
                "expected": PART_SIZE_BYTES,
                "actual": part_size_bytes,
            },
        )
    try:
        uploaded_parts = await storage.list_parts(transfer.object_key, upload_id)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchUpload":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"error_code": "unknown_upload_id"},
            ) from exc
        raise
    part_count = (transfer.size_bytes + PART_SIZE_BYTES - 1) // PART_SIZE_BYTES
    requested = part_numbers if part_numbers is not None else list(range(1, part_count + 1))
    for number in requested:
        if number < 1 or number > part_count:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error_code": "invalid_part_number",
                    "part_number": number,
                    "part_count": part_count,
                },
            )
    missing = [n for n in requested if n not in uploaded_parts]
    part_urls = {n: storage.presign_upload_part(transfer.object_key, upload_id, n) for n in missing}
    return UploadPartsRefreshResponse(
        transfer_id=transfer.id,
        upload_id=upload_id,
        part_size_bytes=PART_SIZE_BYTES,
        part_urls=part_urls,
        uploaded_parts=uploaded_parts,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.presigned_url_ttl_seconds),
    )


async def complete_upload(
    session: AsyncSession,
    principal: Principal,
    storage: StorageProvider,
    transfer: TransferModel,
    size_bytes: int,
    sha256: str,
    upload_id: str | None,
    parts: dict[int, str] | None,
) -> TransferModel:
    """`transfer.size_bytes` (set at creation and checked against the quota,
    DEC-0019) is the source of truth for the expected size — not the
    completion request's `size_bytes` — otherwise a client could declare a
    small size at creation to pass the quota check, then complete with a
    larger real size and silently exceed the quota it was granted (DEC-0025).
    A client-declared `size_bytes` that disagrees with the reservation is
    therefore rejected the same way a storage-side mismatch is."""
    ensure_transfer_access(principal, transfer, "write")
    if size_bytes != transfer.size_bytes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "size_mismatch",
                "expected": transfer.size_bytes,
                "actual": size_bytes,
            },
        )
    if parts:
        if not upload_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "missing_upload_id"},
            )
        await storage.complete_multipart_upload(
            transfer.object_key, upload_id=upload_id, parts=parts
        )
    try:
        head = await storage.head_object(transfer.object_key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "404":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "object_not_found"},
            ) from exc
        raise
    actual_size = head.get("ContentLength")
    if actual_size is not None and actual_size != transfer.size_bytes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "size_mismatch",
                "expected": transfer.size_bytes,
                "actual": actual_size,
            },
        )
    if not parts and transfer.content_md5:
        # Single-PUT path: MinIO/S3 already refused any byte mismatch against
        # the presigned Content-MD5 (DEC-0025). This re-check is defense in
        # depth against a storage backend that enforces it less strictly.
        actual_etag = str(head.get("ETag", "")).strip('"')
        try:
            expected_hex = base64.b64decode(transfer.content_md5).hex()
        except binascii.Error:
            expected_hex = ""
        if expected_hex != actual_etag:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "content_md5_mismatch"},
            )
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


async def _abort_dangling_multipart_uploads(storage: StorageProvider, object_key: str) -> None:
    """A multipart upload never completed for this transfer would otherwise
    leave its parts billed forever in the bucket after the Transfer row
    itself is gone (DEC-0037) — deleting/expiring a transfer is exactly the
    moment we know for certain no one will ever complete it."""
    for upload in await storage.list_multipart_uploads(prefix=object_key):
        if upload["key"] == object_key:
            await storage.abort_multipart_upload(object_key, str(upload["upload_id"]))


async def _do_delete(
    session: AsyncSession, storage: StorageProvider, transfer: TransferModel
) -> None:
    await _abort_dangling_multipart_uploads(storage, transfer.object_key)
    await storage.delete_object(transfer.object_key)
    transfer.status = "deleted"
    transfer.deleted_at = datetime.now(UTC)
    await session.commit()


async def delete_transfer(
    session: AsyncSession, principal: Principal, storage: StorageProvider, transfer: TransferModel
) -> None:
    """Never delete a non-expired transfer without an explicit policy behind it
    (AI/01_AI_OPERATING_REFERENCE.md) — this path is for an explicit user/API
    delete request, not automatic cleanup (see `expire_transfers`, which is
    server-internal and bypasses this check the same way `create_event`
    bypasses `resolve_event_identity` for its own internal callers)."""
    ensure_transfer_access(principal, transfer, "write")
    await _do_delete(session, storage, transfer)


async def abort_stale_multipart_uploads(
    storage: StorageProvider, older_than_days: int, *, dry_run: bool = False
) -> list[dict[str, object]]:
    """Orphan-cleanup worker (DEC-0037): a multipart upload nobody ever came
    back to complete or resume otherwise keeps its parts in the bucket
    forever — this server never persists in-progress multipart state
    server-side, so age (`Initiated`, storage's own record) is the only
    signal available to distinguish "orphaned" from "a client legitimately
    still offline". Abandoning one is never a data loss: the client's next
    attempt gets `409 unknown_upload_id` from `refresh_upload_parts` and
    falls back to a fresh `initiate_upload` (full re-upload, not a hard
    failure)."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    stale = [
        upload
        for upload in await storage.list_multipart_uploads()
        if cast(datetime, upload["initiated"]) < cutoff
    ]
    if not dry_run:
        for upload in stale:
            await storage.abort_multipart_upload(str(upload["key"]), str(upload["upload_id"]))
    return stale


async def expire_transfers(session: AsyncSession, storage: StorageProvider) -> list[TransferModel]:
    """Retention worker (roadmap etape 4.3, DEC-0020): deletes every transfer
    whose `expires_at` has passed and that isn't already deleted, both the
    MinIO object and the DB row. Committing one transfer at a time keeps a
    failure on one object from losing progress already made on the others,
    and re-running this against the same expired set is a no-op since the
    `status != "deleted"` filter excludes rows a previous run already
    cleared. Server-internal (not triggered by a caller), so it deletes
    directly rather than going through `delete_transfer`'s sender/admin
    ownership check."""
    stmt = select(TransferModel).where(
        TransferModel.expires_at.is_not(None),
        TransferModel.expires_at <= datetime.now(UTC),
        TransferModel.status != "deleted",
    )
    result = await session.execute(stmt)
    expired = list(result.scalars().all())
    for transfer in expired:
        await _do_delete(session, storage, transfer)
    return expired
