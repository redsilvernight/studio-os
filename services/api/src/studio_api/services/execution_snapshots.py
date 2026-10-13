"""Immutable execution snapshots (DEC-0199): record once, read, purge by retention.

No HTTP route and no capture here (P04-snapshot-capture). The service never
updates a stored payload: recording the same content again is a no-op that
returns the stored snapshot, recording a different content for the same launch
is refused.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.execution_snapshot import (
    ExecutionSnapshot,
    ExecutionSnapshotPayload,
    SnapshotCaptureStatus,
    check_payload_size,
    content_hash,
)

from studio_api.db.models.execution_snapshot import ExecutionSnapshotModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.settings import get_settings

DEFAULT_PURGE_BATCH = 1000


def _error(code: int, error_code: str, **details: Any) -> HTTPException:
    return HTTPException(code, detail={"error_code": error_code, **details})


def _to_contract(row: ExecutionSnapshotModel) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        id=row.id,
        project_id=row.project_id,
        task_launch_id=row.task_launch_id,
        content_hash=row.content_hash,
        schema_version=row.schema_version,
        capture_status=SnapshotCaptureStatus(row.capture_status),
        capture_reason=row.capture_reason,
        payload=ExecutionSnapshotPayload.model_validate(row.payload),
        created_at=row.created_at,
        retention_until=row.retention_until,
    )


async def _by_launch(
    session: AsyncSession, task_launch_id: uuid.UUID
) -> ExecutionSnapshotModel | None:
    result = await session.scalars(
        select(ExecutionSnapshotModel).where(
            ExecutionSnapshotModel.task_launch_id == task_launch_id
        )
    )
    return result.one_or_none()


async def record_snapshot(
    session: AsyncSession,
    *,
    task_launch_id: uuid.UUID,
    payload: ExecutionSnapshotPayload,
    retention_days: int | None = None,
    now: datetime | None = None,
) -> ExecutionSnapshot:
    """Record the snapshot of one launch attempt, idempotent by content hash."""
    launch = await session.get(TaskLaunchModel, task_launch_id)
    if launch is None:
        raise _error(status.HTTP_404_NOT_FOUND, "task_launch_not_found")
    try:
        check_payload_size(payload)
    except ValueError as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "snapshot_payload_too_large", reason=str(exc)
        ) from exc

    digest = content_hash(payload)
    existing = await _by_launch(session, task_launch_id)
    if existing is None:
        days = retention_days or get_settings().execution_snapshot_retention_days
        created_at = now or datetime.now(UTC)
        await session.execute(
            pg_insert(ExecutionSnapshotModel)
            .values(
                id=uuid.uuid4(),
                project_id=launch.project_id,
                task_launch_id=task_launch_id,
                content_hash=digest,
                schema_version=payload.schema_version,
                capture_status=payload.capture_status.value,
                capture_reason=payload.capture_reason,
                payload=payload.model_dump(mode="json"),
                created_at=created_at,
                retention_until=created_at + timedelta(days=days),
            )
            .on_conflict_do_nothing(constraint="uq_execution_snapshots_launch")
        )
        existing = await _by_launch(session, task_launch_id)
        assert existing is not None
    if existing.content_hash != digest:
        raise _error(
            status.HTTP_409_CONFLICT,
            "execution_snapshot_immutable",
            snapshot_id=str(existing.id),
            content_hash=existing.content_hash,
        )
    return _to_contract(existing)


async def get_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> ExecutionSnapshot | None:
    row = await session.get(ExecutionSnapshotModel, snapshot_id)
    return None if row is None else _to_contract(row)


async def get_snapshot_for_launch(
    session: AsyncSession, task_launch_id: uuid.UUID
) -> ExecutionSnapshot | None:
    row = await _by_launch(session, task_launch_id)
    return None if row is None else _to_contract(row)


async def purge_expired(
    session: AsyncSession, *, now: datetime | None = None, limit: int = DEFAULT_PURGE_BATCH
) -> int:
    """Delete at most `limit` snapshots whose retention has elapsed; returns the
    number deleted. Callers loop until it returns 0."""
    cutoff = now or datetime.now(UTC)
    expired = (
        select(ExecutionSnapshotModel.id)
        .where(ExecutionSnapshotModel.retention_until <= cutoff)
        .order_by(ExecutionSnapshotModel.retention_until)
        .limit(limit)
        .scalar_subquery()
    )
    result = await session.execute(
        delete(ExecutionSnapshotModel)
        .where(ExecutionSnapshotModel.id.in_(expired))
        .returning(ExecutionSnapshotModel.id)
    )
    return len(result.all())
