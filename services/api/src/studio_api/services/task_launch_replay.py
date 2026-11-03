from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.execution_snapshot import (
    ExecutionSnapshot,
    SnapshotCaptureStatus,
    SnapshotResolution,
    SnapshotResourceRef,
    SnapshotRuntimeRef,
    resolution_refs,
)
from studio_contracts.library import LibraryKind
from studio_contracts.task_launch import TERMINAL_STATUSES, TaskLaunchCreate
from studio_contracts.task_launch_replay import (
    ReplayChange,
    ReplayDifference,
    ReplayLimitation,
    ReplayLimitationCode,
    ReplaySubjectKind,
    ReplayVerdict,
    TaskLaunchReplayBasis,
    TaskLaunchReplayConfirmation,
    TaskLaunchReplayPreview,
    limitation,
    preview_digest,
    substitutions,
    verdict_for,
)

from studio_api.db.models.library import LibraryResourceVersionModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.services import execution_snapshots as snapshots_service
from studio_api.services import resolution as resolution_service
from studio_api.services import task_launches as launches_service
from studio_api.services.authz import Principal
from studio_api.settings import Settings

Code = ReplayLimitationCode


def _resource_label(ref: SnapshotResourceRef) -> str:
    return f"v{ref.version} {ref.content_digest}" if ref.content_digest else f"v{ref.version}"


def _runtime_label(ref: SnapshotRuntimeRef | None) -> str | None:
    if ref is None:
        return None
    parts = [ref.matched_stable_key, ref.model_ref or "", ref.capabilities_digest]
    return " ".join(part for part in parts if part)


def _change(recorded: str | None, current: str | None) -> ReplayChange:
    if recorded == current:
        return ReplayChange.UNCHANGED
    if recorded is None:
        return ReplayChange.ADDED
    if current is None:
        return ReplayChange.REMOVED
    return ReplayChange.CHANGED


async def _missing_versions(
    session: AsyncSession, refs: Iterable[SnapshotResourceRef]
) -> set[tuple[str, int]]:
    wanted = {(ref.resource_id, ref.version) for ref in refs}
    if not wanted:
        return set()
    result = await session.execute(
        select(LibraryResourceVersionModel.resource_id, LibraryResourceVersionModel.version).where(
            tuple_(
                LibraryResourceVersionModel.resource_id, LibraryResourceVersionModel.version
            ).in_(list(wanted))
        )
    )
    present = {(row.resource_id, row.version) for row in result}
    return {(str(resource_id), version) for resource_id, version in wanted - present}


def _resource_differences(
    recorded: SnapshotResolution,
    current: SnapshotResolution | None,
    missing: set[tuple[str, int]],
) -> tuple[list[ReplayDifference], list[ReplayLimitation]]:
    def key(ref: SnapshotResourceRef) -> tuple[str, str]:
        return (ref.role.value, ref.stable_key)

    before = {key(ref): ref for ref in recorded.resources}
    after = {} if current is None else {key(ref): ref for ref in current.resources}
    differences: list[ReplayDifference] = []
    limitations: list[ReplayLimitation] = []
    for item in sorted(before.keys() | after.keys()):
        old, new = before.get(item), after.get(item)
        ref = old or new
        assert ref is not None
        old_label = None if old is None else _resource_label(old)
        new_label = None if new is None else _resource_label(new)
        change = _change(old_label, new_label)
        if old is not None and (str(old.resource_id), old.version) in missing:
            change = ReplayChange.UNAVAILABLE
            limitations.append(limitation(Code.LIBRARY_VERSION_UNAVAILABLE, old.stable_key))
        differences.append(
            ReplayDifference(
                subject_kind=ReplaySubjectKind.RESOURCE,
                role=ref.role,
                stable_key=ref.stable_key,
                recorded=old_label,
                current=new_label,
                change=change,
            )
        )
    old_runtime = _runtime_label(recorded.runtime)
    new_runtime = None if current is None else _runtime_label(current.runtime)
    if old_runtime is not None or new_runtime is not None:
        differences.append(
            ReplayDifference(
                subject_kind=ReplaySubjectKind.RUNTIME,
                stable_key="runtime",
                recorded=old_runtime,
                current=new_runtime,
                change=_change(old_runtime, new_runtime),
            )
        )
    return differences, limitations


async def _admission(
    session: AsyncSession, principal: Principal, launch: TaskLaunchModel, settings: Settings
) -> ReplayLimitation | None:
    if principal.role != Role.ADMIN and launch.requested_by_user_id != principal.user.id:
        return limitation(Code.NOT_AUTHORIZED, "requester")
    machine = await session.get(MachineModel, launch.machine_id)
    task = await session.get(TaskModel, launch.task_id)
    if machine is None or task is None:
        return limitation(Code.TARGET_NOT_ADMISSIBLE, "launch_target_not_found")
    launch_in = TaskLaunchCreate(
        task_id=launch.task_id,
        machine_id=launch.machine_id,
        harness_id=launch.harness_id,
        agent_stable_key=launch.agent_stable_key,
    )
    try:
        await launches_service.authorize_create(
            session,
            principal,
            launch.project_id,
            task,
            machine,
            launch_in,
            settings,
            datetime.now(UTC),
        )
    except HTTPException as refused:
        detail: dict[str, Any] = refused.detail if isinstance(refused.detail, dict) else {}
        subject = str(detail.get("error_code") or refused.status_code)
        code = (
            Code.NOT_AUTHORIZED
            if refused.status_code == status.HTTP_403_FORBIDDEN
            else Code.TARGET_NOT_ADMISSIBLE
        )
        return limitation(code, subject)
    return None


async def _current_resolution(
    session: AsyncSession, principal: Principal, launch: TaskLaunchModel
) -> SnapshotResolution | None:
    if launch.agent_stable_key is None:
        return None
    definition = await resolution_service.resolve_full(
        session,
        principal,
        LibraryKind.AGENT_DEFINITION,
        launch.agent_stable_key,
        launch.project_id,
    )
    return resolution_refs(definition)


def _snapshot_limitations(snapshot: ExecutionSnapshot) -> list[ReplayLimitation]:
    payload = snapshot.payload
    found: list[ReplayLimitation] = []
    if payload.capture_status is SnapshotCaptureStatus.FAILED:
        found.append(limitation(Code.SNAPSHOT_CAPTURE_FAILED))
    if payload.resolution is None:
        found.append(limitation(Code.RESOLUTION_UNRECORDED))
    applied = payload.applied
    if applied is None or applied.git_sha is None:
        found.append(limitation(Code.SOURCE_GIT_UNRECORDED))
    if applied is not None and applied.git_dirty:
        found.append(limitation(Code.SOURCE_WORKTREE_DIRTY))
    if (payload.resolution is not None and payload.resolution.profile is not None) or (
        applied is not None and applied.profile is not None
    ):
        found.append(limitation(Code.PROFILE_RECHECKED_ON_MACHINE))
    return found


async def compute_preview(
    session: AsyncSession, principal: Principal, launch: TaskLaunchModel, settings: Settings
) -> TaskLaunchReplayPreview:
    """Read-only: what a retry of this terminal attempt would use today,
    compared with its execution snapshot. Creates nothing, writes nothing."""
    limitations: list[ReplayLimitation] = []
    differences: list[ReplayDifference] = []
    if launch.status not in {s.value for s in TERMINAL_STATUSES}:
        limitations.append(limitation(Code.LAUNCH_NOT_TERMINAL, launch.status))
    existing = await launches_service.existing_retry(session, launch)
    if existing is not None:
        limitations.append(limitation(Code.ALREADY_RETRIED, str(existing.id)))
    if (refusal := await _admission(session, principal, launch, settings)) is not None:
        limitations.append(refusal)
    snapshot = await snapshots_service.get_snapshot_for_launch(session, launch.id)
    if snapshot is None:
        limitations.append(limitation(Code.SNAPSHOT_MISSING))
    else:
        limitations.extend(_snapshot_limitations(snapshot))
        applied = snapshot.payload.applied
        recorded_harness = None if applied is None else applied.harness_id
        differences.append(
            ReplayDifference(
                subject_kind=ReplaySubjectKind.HARNESS,
                stable_key="harness",
                recorded=recorded_harness,
                current=launch.harness_id,
                change=_change(recorded_harness, launch.harness_id),
            )
        )
        recorded = snapshot.payload.resolution
        current: SnapshotResolution | None = None
        try:
            current = await _current_resolution(session, principal, launch)
        except HTTPException as failure:
            detail: dict[str, Any] = failure.detail if isinstance(failure.detail, dict) else {}
            limitations.append(
                limitation(Code.AGENT_UNRESOLVABLE, str(detail.get("error_code") or "resolution"))
            )
        if recorded is not None:
            missing = await _missing_versions(session, recorded.resources)
            resources, unavailable = _resource_differences(recorded, current, missing)
            differences.extend(resources)
            limitations.extend(unavailable)
    limitations.append(limitation(Code.GIT_STATE_NOT_PINNED))
    limitations.append(limitation(Code.OUTPUT_NOT_REPRODUCIBLE))
    limitations.sort(key=lambda item: (item.code.value, item.subject or ""))
    verdict = verdict_for(limitations)
    snapshot_hash = None if snapshot is None else snapshot.content_hash
    return TaskLaunchReplayPreview(
        source_launch_id=launch.id,
        snapshot_id=None if snapshot is None else snapshot.id,
        snapshot_content_hash=snapshot_hash,
        verdict=verdict,
        differences=differences,
        limitations=limitations,
        preview_digest=preview_digest(
            source_launch_id=launch.id,
            snapshot_content_hash=snapshot_hash,
            verdict=verdict,
            differences=differences,
            limitations=limitations,
        ),
        generated_at=datetime.now(UTC),
    )


async def confirm_replay(
    session: AsyncSession,
    principal: Principal,
    launch: TaskLaunchModel,
    confirmation: TaskLaunchReplayConfirmation,
    settings: Settings,
) -> dict[str, Any]:
    """Recompute the preview at retry time: a refusal or a preview that is not
    the one the requester accepted creates nothing. Returns the basis stored on
    the new attempt."""
    preview = await compute_preview(session, principal, launch, settings)
    if preview.verdict is ReplayVerdict.REFUSED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "replay_refused",
                "codes": [
                    item.code.value
                    for item in preview.limitations
                    if item.severity.value == "refusal"
                ],
            },
        )
    if (
        confirmation.snapshot_content_hash != preview.snapshot_content_hash
        or confirmation.preview_digest != preview.preview_digest
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "replay_preview_stale", "preview_digest": preview.preview_digest},
        )
    assert preview.snapshot_content_hash is not None
    basis = TaskLaunchReplayBasis(
        source_launch_id=launch.id,
        snapshot_content_hash=preview.snapshot_content_hash,
        preview_digest=preview.preview_digest,
        verdict=preview.verdict,
        substitutions=substitutions(preview.differences),
        limitation_codes=[item.code for item in preview.limitations],
    )
    return basis.model_dump(mode="json")
