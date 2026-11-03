"""Execution snapshot storage and service (P04-snapshot-contract, migration 0032):
idempotent by content hash, immutable, independent from current Library
resources, purged by retention."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models import (
    ExecutionSnapshotModel,
    LibraryResourceModel,
    LibraryResourceVersionModel,
    MachineModel,
    ProjectModel,
    TaskLaunchModel,
    TaskModel,
)
from studio_api.services import execution_snapshots as service
from studio_api.settings import get_settings
from studio_contracts.execution_snapshot import (
    ExecutionSnapshotPayload,
    SnapshotAppliedParameters,
    SnapshotCaptureError,
    SnapshotCaptureErrorCode,
    SnapshotCaptureStatus,
    SnapshotResolution,
    SnapshotResourceRef,
    SnapshotResourceRole,
    content_hash,
    digest_of,
)
from studio_contracts.library import LibraryKind, LibraryScope, VersionOrigin

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


async def _launch(session: AsyncSession, project: ProjectModel, machine: MachineModel) -> uuid.UUID:
    task = TaskModel(project_id=project.id, title="Snapshot task")
    session.add(task)
    await session.flush()
    launch = TaskLaunchModel(
        project_id=project.id,
        task_id=task.id,
        machine_id=machine.id,
        requested_by_user_id=machine.owner_user_id,
        harness_id="claude-code",
        expires_at=NOW + timedelta(hours=1),
    )
    session.add(launch)
    await session.flush()
    return launch.id


def _payload(
    resource_id: uuid.UUID | None = None, harness_version: str = "2.1.0"
) -> ExecutionSnapshotPayload:
    return ExecutionSnapshotPayload(
        capture_status=SnapshotCaptureStatus.OK,
        resolution=SnapshotResolution(
            agent_stable_key="builder",
            resources=[
                SnapshotResourceRef(
                    role=SnapshotResourceRole.AGENT,
                    resource_id=resource_id or uuid.uuid4(),
                    kind=LibraryKind.AGENT_DEFINITION,
                    stable_key="builder",
                    scope=LibraryScope.STUDIO,
                    version=1,
                    version_origin=VersionOrigin.ACTIVE,
                    content_digest=digest_of({"prompt": "p"}),
                )
            ],
        ),
        applied=SnapshotAppliedParameters(
            harness_id="claude-code", harness_version=harness_version, git_sha="b" * 40
        ),
    )


async def test_record_is_idempotent_by_content_hash(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    launch_id = await _launch(db_session, project, machine[0])
    payload = _payload()
    first = await service.record_snapshot(
        db_session, task_launch_id=launch_id, payload=payload, now=NOW
    )
    again = await service.record_snapshot(
        db_session,
        task_launch_id=launch_id,
        payload=_payload(
            payload.resolution.resources[0].resource_id  # type: ignore[union-attr]
        ),
        now=NOW + timedelta(minutes=5),
    )
    assert again.id == first.id
    assert first.content_hash == content_hash(payload)
    assert first.project_id == project.id
    assert first.retention_until == NOW + timedelta(
        days=get_settings().execution_snapshot_retention_days
    )
    rows = await db_session.scalars(
        select(ExecutionSnapshotModel).where(ExecutionSnapshotModel.task_launch_id == launch_id)
    )
    assert len(rows.all()) == 1
    fetched = await service.get_snapshot(db_session, first.id)
    assert fetched == first
    assert await service.get_snapshot_for_launch(db_session, launch_id) == first


async def test_same_configuration_hashes_identically_across_launches(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    resource_id = uuid.uuid4()
    a = await service.record_snapshot(
        db_session,
        task_launch_id=await _launch(db_session, project, machine[0]),
        payload=_payload(resource_id),
        now=NOW,
    )
    b = await service.record_snapshot(
        db_session,
        task_launch_id=await _launch(db_session, project, machine[0]),
        payload=_payload(resource_id),
        now=NOW,
    )
    assert a.id != b.id and a.content_hash == b.content_hash


async def test_snapshot_is_immutable(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    launch_id = await _launch(db_session, project, machine[0])
    first = await service.record_snapshot(
        db_session, task_launch_id=launch_id, payload=_payload(), now=NOW
    )
    with pytest.raises(HTTPException) as caught:
        await service.record_snapshot(
            db_session, task_launch_id=launch_id, payload=_payload(harness_version="9.9.9"), now=NOW
        )
    assert caught.value.status_code == 409
    detail: dict[str, Any] = caught.value.detail  # type: ignore[assignment]
    assert detail["error_code"] == "execution_snapshot_immutable"
    stored = await service.get_snapshot_for_launch(db_session, launch_id)
    assert stored == first


async def test_partial_capture_keeps_explicit_reason(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    launch_id = await _launch(db_session, project, machine[0])
    payload = ExecutionSnapshotPayload(
        capture_status=SnapshotCaptureStatus.PARTIAL,
        applied=SnapshotAppliedParameters(harness_id="claude-code"),
        capture_errors=[SnapshotCaptureError(code=SnapshotCaptureErrorCode.RESOLUTION_UNAVAILABLE)],
    )
    snapshot = await service.record_snapshot(
        db_session, task_launch_id=launch_id, payload=payload, now=NOW
    )
    assert snapshot.capture_status is SnapshotCaptureStatus.PARTIAL
    assert snapshot.capture_reason == "resolution_unavailable"


async def test_unknown_launch_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as caught:
        await service.record_snapshot(db_session, task_launch_id=uuid.uuid4(), payload=_payload())
    assert caught.value.status_code == 404


async def test_deleting_library_resource_keeps_snapshot(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    resource = LibraryResourceModel(
        kind=LibraryKind.AGENT_DEFINITION.value,
        stable_key=f"snap-{uuid.uuid4().hex[:8]}",
        scope=LibraryScope.STUDIO.value,
        status="active",
        active_version=1,
    )
    db_session.add(resource)
    await db_session.flush()
    db_session.add(
        LibraryResourceVersionModel(
            resource_id=resource.id, version=1, title="t", content={"prompt": "p"}
        )
    )
    await db_session.flush()
    launch_id = await _launch(db_session, project, machine[0])
    recorded = await service.record_snapshot(
        db_session, task_launch_id=launch_id, payload=_payload(resource.id), now=NOW
    )

    await db_session.execute(
        delete(LibraryResourceVersionModel).where(
            LibraryResourceVersionModel.resource_id == resource.id
        )
    )
    await db_session.execute(
        delete(LibraryResourceModel).where(LibraryResourceModel.id == resource.id)
    )
    await db_session.flush()
    db_session.expire_all()

    kept = await service.get_snapshot(db_session, recorded.id)
    assert kept == recorded
    assert kept is not None and kept.payload.resolution is not None
    assert kept.payload.resolution.resources[0].resource_id == resource.id


async def test_purge_removes_only_expired_snapshots(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    old = await service.record_snapshot(
        db_session,
        task_launch_id=await _launch(db_session, project, machine[0]),
        payload=_payload(),
        retention_days=1,
        now=NOW - timedelta(days=2),
    )
    fresh = await service.record_snapshot(
        db_session,
        task_launch_id=await _launch(db_session, project, machine[0]),
        payload=_payload(),
        retention_days=30,
        now=NOW,
    )
    assert await service.purge_expired(db_session, now=NOW) >= 1
    assert await service.get_snapshot(db_session, old.id) is None
    assert await service.get_snapshot(db_session, fresh.id) is not None
    assert await service.purge_expired(db_session, now=NOW) == 0


async def test_sql_refuses_inconsistent_rows(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    launch_id = await _launch(db_session, project, machine[0])
    for fields in (
        {"capture_status": "ok", "capture_reason": "internal"},
        {"capture_status": "failed", "capture_reason": None},
        {"capture_status": "unknown", "capture_reason": "x"},
        {"capture_status": "ok", "capture_reason": None, "content_hash": "md5:abc"},
    ):
        values: dict[str, Any] = {
            "project_id": project.id,
            "task_launch_id": launch_id,
            "content_hash": digest_of(1),
            "schema_version": 1,
            "payload": {},
            "created_at": NOW,
            "retention_until": NOW + timedelta(days=1),
            **fields,
        }
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(ExecutionSnapshotModel(**values))
                await db_session.flush()
