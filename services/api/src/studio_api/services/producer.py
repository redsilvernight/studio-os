from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.builds import ProducerJobKind, ProducerJobRequest
from studio_contracts.events import EventCreate, EventType

from studio_api.db.models.build import ProducerJobModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.services import claims as claims_service
from studio_api.services import events as events_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_project_access,
    project_visibility_clause,
)

_MAX_TASKS_SCANNED = 500
_MAX_RANKING_ENTRIES = 50
_MAX_GROUPS = 20


def _paths_overlap(a_path: str, a_type: str, b_path: str, b_type: str) -> bool:
    """Same disjointness rule as `claims._conflicts` (the canonical
    definition — folder claim overlaps a descendant file claim, same path
    always overlaps). Kept local so the Producer stays a pure read over
    `list_claims` instead of issuing one `has_conflict` query per claim."""
    if a_path == b_path:
        return True
    if a_type == "folder" and b_path.startswith(a_path.rstrip("/") + "/"):
        return True
    if b_type == "folder" and a_path.startswith(b_path.rstrip("/") + "/"):
        return True
    return False


def _open_tasks(tasks: list[TaskModel]) -> list[TaskModel]:
    return [t for t in tasks if t.status in ("created", "in_progress", "blocked")]


async def _priority_analysis(tasks: list[TaskModel]) -> dict[str, object]:
    """In-progress (oldest first — closest to done), then created (oldest
    first — longest waiting), then blocked last (needs unblocking before
    scheduling). Completed tasks are not scheduled work."""
    rank = {"in_progress": 0, "created": 1, "blocked": 2}
    ordered = sorted(_open_tasks(tasks), key=lambda t: (rank[t.status], t.created_at))
    ranking = [
        {
            "task_id": str(t.id),
            "title": t.title,
            "status": t.status,
            "reason": (
                "in progress — finish before starting new work"
                if t.status == "in_progress"
                else "waiting — longest-waiting first"
                if t.status == "created"
                else "blocked — unblock before scheduling"
            ),
        }
        for t in ordered[:_MAX_RANKING_ENTRIES]
    ]
    return {"ranking": ranking}


async def _blocker_detection(
    session: AsyncSession, principal: Principal, project_id: UUID, tasks: list[TaskModel]
) -> dict[str, object]:
    blocked_tasks: list[dict[str, object]] = [
        {"task_id": str(t.id), "title": t.title, "reason": "task status is blocked"}
        for t in tasks
        if t.status == "blocked"
    ]
    blockers: list[dict[str, object]] = list(blocked_tasks)
    claims = await claims_service.list_claims(session, principal, project_id=project_id)
    now = datetime.now(UTC)
    active = [c for c in claims if c.status == "active" and c.expires_at > now]
    seen: set[tuple[str, str]] = set()
    for i, first in enumerate(active):
        for second in active[i + 1 :]:
            if first.claimed_by_machine_id == second.claimed_by_machine_id:
                continue
            if not _paths_overlap(
                first.resource_path,
                first.resource_type,
                second.resource_path,
                second.resource_type,
            ):
                continue
            key = (str(first.id), str(second.id))
            if key in seen:
                continue
            seen.add(key)
            blockers.append(
                {
                    "reason": "conflicting active claims on overlapping paths",
                    "resource_path": first.resource_path,
                    "claim_ids": [str(first.id), str(second.id)],
                }
            )
    return {"blockers": blockers}


async def _parallelization(
    session: AsyncSession, principal: Principal, project_id: UUID, tasks: list[TaskModel]
) -> dict[str, object]:
    """Greedy groups of schedulable tasks (created/in_progress, never
    blocked) whose claimed resource paths are pairwise disjoint — safe to
    run concurrently without tripping a claim conflict."""
    claims = await claims_service.list_claims(session, principal, project_id=project_id)
    now = datetime.now(UTC)
    by_task: dict[str, list[tuple[str, str]]] = {}
    for claim in claims:
        if claim.task_id is None or claim.status != "active" or claim.expires_at <= now:
            continue
        by_task.setdefault(str(claim.task_id), []).append(
            (claim.resource_path, claim.resource_type)
        )
    candidates = [t for t in _open_tasks(tasks) if t.status != "blocked"]
    groups: list[list[dict[str, str]]] = []
    group_paths: list[list[tuple[str, str]]] = []
    for task in candidates:
        task_paths = by_task.get(str(task.id), [])
        placed = False
        for group, paths in zip(groups, group_paths, strict=True):
            if all(
                not _paths_overlap(path, kind, other, other_kind)
                for path, kind in task_paths
                for other, other_kind in paths
            ):
                group.append({"task_id": str(task.id), "title": task.title})
                paths.extend(task_paths)
                placed = True
                break
        if not placed:
            if len(groups) >= _MAX_GROUPS:
                break
            groups.append([{"task_id": str(task.id), "title": task.title}])
            group_paths.append(list(task_paths))
    return {"groups": groups}


def _decomposition(task: TaskModel) -> dict[str, object]:
    """Proposes sub-tasks from an itemized description (`-`, `*`, `1.`,
    `[ ]` bullets) — a deterministic v1 heuristic, not an LLM plan. The
    caller creates the sub-tasks itself via `POST /tasks`; nothing is
    written here. No itemizable structure → empty proposal with a note,
    never invented work."""
    import re

    lines = (task.description or "").splitlines()
    items = [
        re.sub(r"^(\s*(?:[-*]|\d+[.)]|\[ \])\s*)", "", line).strip()
        for line in lines
        if re.match(r"^\s*(?:[-*]|\d+[.)]|\[ \])\s*\S", line)
    ]
    seen: set[str] = set()
    proposed = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            proposed.append({"title": item})
    result: dict[str, object] = {
        "source_task_id": str(task.id),
        "proposed_subtasks": proposed,
    }
    if not proposed:
        result["note"] = (
            "no itemized structure found in the task description — "
            "nothing proposed; itemize the description to get sub-tasks"
        )
    return result


async def list_producer_jobs(
    session: AsyncSession, principal: Principal, project_id: UUID | None = None, limit: int = 100
) -> list[ProducerJobModel]:
    stmt = select(ProducerJobModel).order_by(ProducerJobModel.created_at.desc()).limit(limit)
    if project_id is not None:
        ensure_project_access(principal, project_id)
        stmt = stmt.where(ProducerJobModel.project_id == project_id)
    elif (visible := project_visibility_clause(principal, ProducerJobModel.project_id)) is not None:
        stmt = stmt.where(visible)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_producer_job(
    session: AsyncSession, principal: Principal, job_id: UUID
) -> ProducerJobModel | None:
    job = await session.get(ProducerJobModel, job_id)
    if job is not None:
        ensure_project_access(principal, job.project_id)
    return job


def authorize_request(principal: Principal, project_id: UUID) -> None:
    """Project then role check of a job request, run ahead of the
    idempotency replay short-circuit (DEC-0036, DEC-0100 §12)."""
    ensure_project_access(principal, project_id, "write")
    ensure_can_write(principal, "producer_job")


def _producer_event_id(job_id: UUID, status: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"studio-producer:{job_id}:{status}")


async def request_producer_job(
    session: AsyncSession, principal: Principal, job_in: ProducerJobRequest
) -> ProducerJobModel:
    """Runs the analysis synchronously and bounded (v1) — the returned job
    is already `completed`/`failed`. Creates the row, never mutates
    `Task`/`ResourceClaim`: a `decomposition` result is a proposal the
    caller materializes via `POST /tasks`."""
    authorize_request(principal, job_in.project_id)
    if job_in.kind == ProducerJobKind.DECOMPOSITION and job_in.task_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "task_required",
                "message": "decomposition requires a task_id",
            },
        )
    project = await session.get(ProjectModel, job_in.project_id)
    if project is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "project_not_found", "message": "project not found"},
        )
    task: TaskModel | None = None
    if job_in.task_id is not None:
        task = await tasks_service.get_task(session, job_in.task_id)
        if task is None or task.project_id != job_in.project_id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={"error_code": "task_not_found", "message": "task not found in project"},
            )

    job = ProducerJobModel(
        project_id=job_in.project_id,
        kind=job_in.kind.value,
        status="running",
        task_id=job_in.task_id,
        created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()

    await events_service.create_event(
        session,
        EventCreate(
            event_id=_producer_event_id(job.id, "requested"),
            event_type=EventType.PRODUCER_JOB_REQUESTED,
            project_id=job_in.project_id,
            task_id=job_in.task_id,
            machine_id=principal.machine.id,
            actor_type="system",
            actor_id=principal.machine.id,
            client_timestamp=datetime.now(UTC),
            payload={"job_id": str(job.id), "kind": job_in.kind.value},
        ),
    )

    try:
        tasks = await tasks_service.list_tasks(
            session, principal, project_id=job_in.project_id, limit=_MAX_TASKS_SCANNED
        )
        if job_in.kind == ProducerJobKind.PRIORITY_ANALYSIS:
            result = await _priority_analysis(tasks)
        elif job_in.kind == ProducerJobKind.BLOCKER_DETECTION:
            result = await _blocker_detection(session, principal, job_in.project_id, tasks)
        elif job_in.kind == ProducerJobKind.PARALLELIZATION:
            result = await _parallelization(session, principal, job_in.project_id, tasks)
        else:
            assert task is not None
            result = _decomposition(task)
        job.result = result
        job.status = "completed"
        final_type = EventType.PRODUCER_JOB_COMPLETED
    except Exception as exc:
        job.result = {}
        job.error = f"{type(exc).__name__}: {exc}"
        job.status = "failed"
        final_type = EventType.PRODUCER_JOB_FAILED
    job.completed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(job)

    await events_service.create_event(
        session,
        EventCreate(
            event_id=_producer_event_id(job.id, job.status),
            event_type=final_type,
            project_id=job_in.project_id,
            task_id=job_in.task_id,
            machine_id=principal.machine.id,
            actor_type="system",
            actor_id=principal.machine.id,
            client_timestamp=datetime.now(UTC),
            payload={"job_id": str(job.id), "kind": job_in.kind.value, "status": job.status},
        ),
    )
    return job
