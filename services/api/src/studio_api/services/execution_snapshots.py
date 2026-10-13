"""Immutable execution snapshots (DEC-0199): record once, read, purge by retention.

Routes: `POST`/`GET /api/v1/task-launches/{id}/snapshot`; the capture itself
runs on the machine (`studio_client.daemon.launch_snapshot`). The service never
updates a stored payload: recording the same content again is a no-op that
returns the stored snapshot, recording a different content for the same launch
is refused.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
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
from studio_contracts.local.common import (
    contains_absolute_path,
    contains_secret_material,
    is_secret_key_name,
)

from studio_api.db.models.execution_snapshot import ExecutionSnapshotModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.services.authz import Principal, ensure_project_access
from studio_api.services.task_launches import authorize_report
from studio_api.settings import get_settings

DEFAULT_PURGE_BATCH = 1000


def _error(code: int, error_code: str, **details: Any) -> HTTPException:
    return HTTPException(code, detail={"error_code": error_code, **details})


SNAPSHOT_REFUSED = "execution_snapshot_refused"
MAX_REFUSAL_DETAILS = 20


def _suspect_values(value: Any, path: str = "$") -> Iterator[dict[str, str]]:
    if isinstance(value, str):
        if contains_secret_material(value):
            yield {"path": path, "pattern": "credential_material"}
        elif contains_absolute_path(value):
            yield {"path": path, "pattern": "absolute_path"}
    elif isinstance(value, dict):
        for key, item in value.items():
            name = str(key)
            if is_secret_key_name(name) or not _safe_key(name):
                yield {"path": path, "pattern": "secret_field_name"}
                continue
            yield from _suspect_values(item, f"{path}.{name}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _suspect_values(item, f"{path}[{index}]")


def _safe_key(name: str) -> bool:
    return not contains_secret_material(name) and not contains_absolute_path(name)


def _loc(loc: tuple[int | str, ...]) -> str:
    return "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in loc)


def parse_snapshot_body(body: Any) -> ExecutionSnapshotPayload:
    """Validate a posted snapshot without ever echoing it: a refusal names the
    path and a closed pattern, never the value (FastAPI's default 422 would
    return the whole body as `input`)."""
    details = list(_suspect_values(body))
    if not details:
        try:
            return ExecutionSnapshotPayload.model_validate(body)
        except ValidationError as exc:
            details = [
                {"path": _loc(tuple(error["loc"])), "pattern": str(error["type"])}
                for error in exc.errors(include_input=False, include_context=False)
            ]
    raise _error(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        SNAPSHOT_REFUSED,
        details=details[:MAX_REFUSAL_DETAILS],
    )


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


async def submit_launch_snapshot(
    session: AsyncSession,
    principal: Principal,
    launch: TaskLaunchModel,
    payload: ExecutionSnapshotPayload,
) -> ExecutionSnapshot:
    """HTTP path of `record_snapshot`: only the launch's target machine, with
    its durable credential (launch credentials are not on the allowlist)."""
    authorize_report(principal, launch)
    ensure_project_access(principal, launch.project_id, "write")
    snapshot = await record_snapshot(session, task_launch_id=launch.id, payload=payload)
    await session.commit()
    return snapshot


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
