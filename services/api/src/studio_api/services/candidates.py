"""Candidate tasks for a start with no explicit task (AIB-G): the active
roadmap's current-step linked tasks first, then the project's other unclaimed
tasks — bounded, ordered and explained (`why`), never a claim.

Consumed by `studio_start_work` (task 9dff9368); exposed to nobody directly
yet, so it carries no HTTP/MCP surface of its own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.project_context import DEFAULT_LIMIT, Why
from studio_contracts.tasks import TaskStatus

from studio_api.db.models.task import TaskModel
from studio_api.services import project_context_roadmap
from studio_api.services.authz import Principal, ensure_project_access


@dataclass(frozen=True)
class CandidateTask:
    """One task a fresh start could pick up, with the relation that surfaced
    it: `active_roadmap` (current step, the facade's deterministic order) or
    `project_scope` (another unclaimed project task, most recently updated
    first)."""

    task: TaskModel
    why: Why


def _candidate_clause() -> tuple[object, ...]:
    """Unclaimed and not finished — the work a fresh start can take."""
    return (
        TaskModel.claimed_by_machine_id.is_(None),
        TaskModel.status != TaskStatus.COMPLETED.value,
    )


async def list_candidate_tasks(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    limit: int = DEFAULT_LIMIT,
) -> list[CandidateTask]:
    """Candidates for `project_id`, capped at `limit` (0 returns none). The
    roadmap tier keeps the facade's deterministic order; the project tier is
    most recently updated first. A dangling or foreign linked id is skipped,
    never leaked."""
    ensure_project_access(principal, project_id, "read")
    if limit <= 0:
        return []

    candidates: list[CandidateTask] = []
    seen: set[uuid.UUID] = set()

    linked_ids = await project_context_roadmap.current_step_linked_task_ids(
        session, principal, project_id
    )
    if linked_ids:
        stmt = select(TaskModel).where(
            TaskModel.id.in_(linked_ids),
            TaskModel.project_id == project_id,
            *_candidate_clause(),
        )
        by_id = {task.id: task for task in (await session.execute(stmt)).scalars().all()}
        for task_id in linked_ids:
            task = by_id.get(task_id)
            if task is None:
                continue
            candidates.append(CandidateTask(task, Why(reason="active_roadmap")))
            seen.add(task.id)
            if len(candidates) >= limit:
                return candidates

    stmt = (
        select(TaskModel)
        .where(TaskModel.project_id == project_id, *_candidate_clause())
        .order_by(TaskModel.updated_at.desc(), TaskModel.id)
        .limit(limit + len(seen))
    )
    for task in (await session.execute(stmt)).scalars().all():
        if len(candidates) >= limit:
            break
        if task.id in seen:
            continue
        candidates.append(CandidateTask(task, Why(reason="project_scope")))
    return candidates
