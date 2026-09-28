"""`studio_start_work` (L2, DEC-0159): start or resume work on a task in one
call, or — with no task — return the project context and the candidate tasks,
claiming nothing (AIB-G).

Composes the existing claim, session, project-context and candidate services.
No new table, no new event type, and `prepare_context` gains no side effect
(DEC-0080). Replay-safe two ways: the route's `Idempotency-Key` returns the
original result without re-running, and each composed step is itself
idempotent (claim is a no-op for the same machine/agent, session resume
reuses the open session). Not a single database transaction: the composed
services own their own commits (the constraint the P0 audit recorded), so a
mid-call failure converges on retry rather than rolling everything back.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.project_context import OBJECTIVE_MAX_CHARS
from studio_contracts.sessions import WorkSession, WorkSessionCreate
from studio_contracts.start_work import (
    StartWorkCandidate,
    StartWorkRequest,
    StartWorkResult,
)
from studio_contracts.tasks import Task, TaskStatus

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import candidates as candidates_service
from studio_api.services import project_context as context_service
from studio_api.services import sessions as sessions_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_project_access,
)
from studio_api.settings import Settings


async def authorize_start_work(
    session: AsyncSession, principal: Principal, request: StartWorkRequest
) -> None:
    """Project then role check, plus agent ownership, run ahead of the
    idempotency replay short-circuit (DEC-0036). The task, when named, must
    belong to the given project — a foreign or unknown task is a plain `404`,
    never an existence oracle beyond project access."""
    ensure_project_access(principal, request.project_id, "write")
    ensure_can_write(principal, "start_work")
    agent = await session.get(AgentModel, request.agent_id)
    if agent is None or agent.machine_id != principal.machine.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "actor_not_owned",
                "message": "agent_id must be an agent attached to the authenticated machine",
            },
        )
    if request.task_id is not None:
        task = await tasks_service.get_task(session, request.task_id)
        if task is None or task.project_id != request.project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")


def _default_objective(request: StartWorkRequest, task_title: str | None) -> str:
    if request.objective is not None:
        return request.objective
    base = f"reprendre la tache {task_title}" if task_title is not None else "vue projet"
    return base[:OBJECTIVE_MAX_CHARS]


def _session_contract(work_session: WorkSessionModel, settings: Settings) -> WorkSession:
    """Session reads carry derived presence (C1): `status` and `expires_at`
    computed at read time, exactly like the sessions router."""
    return WorkSession.model_validate(work_session).model_copy(
        update={
            "status": sessions_service.derive_session_status(work_session, settings),
            "expires_at": sessions_service.derive_session_expiry(work_session, settings),
        }
    )


async def start_work(
    session: AsyncSession,
    principal: Principal,
    request: StartWorkRequest,
    settings: Settings,
) -> StartWorkResult:
    """Run the composite. Caller has already run `authorize_start_work`."""
    if request.task_id is not None:
        task = await tasks_service.get_task(session, request.task_id)
        if task is None or task.project_id != request.project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
        claimed = await tasks_service.claim_task(
            session, principal, task, principal.machine.id, request.agent_id
        )
        work_session, resumed = await sessions_service.resume_or_start_session(
            session,
            principal,
            WorkSessionCreate(
                task_id=claimed.id,
                machine_id=principal.machine.id,
                agent_id=request.agent_id,
            ),
            settings,
        )
        context = await context_service.prepare_project_context(
            session,
            principal,
            request.project_id,
            _default_objective(request, claimed.title),
            task_id=claimed.id,
            files=request.files,
            limit=request.limit,
            max_chars=request.max_chars,
            agent_stable_key=request.agent_stable_key,
        )
        return StartWorkResult(
            task=Task.model_validate(claimed),
            session=_session_contract(work_session, settings),
            claimed=True,
            resumed=resumed,
            prepared_context=context,
        )

    context = await context_service.prepare_project_context(
        session,
        principal,
        request.project_id,
        _default_objective(request, None),
        files=request.files,
        limit=request.limit,
        max_chars=request.max_chars,
        agent_stable_key=request.agent_stable_key,
    )
    candidates = await candidates_service.list_candidate_tasks(
        session, principal, request.project_id, limit=request.limit
    )
    return StartWorkResult(
        prepared_context=context,
        candidates=[
            StartWorkCandidate(
                task_id=candidate.task.id,
                title=candidate.task.title,
                status=TaskStatus(candidate.task.status),
                why=candidate.why,
            )
            for candidate in candidates
        ],
    )
