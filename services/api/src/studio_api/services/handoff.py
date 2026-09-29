"""`studio_handoff` (L3, additive): close a work session in one call,
updating the task status, releasing all claims for the task, logging
the AI work (if agent_id provided), and ending the session.

Composes existing services: task update, claims release, AI work log,
session end. No new table, no new event type — the composed services
own their own commits, so a mid-call failure converges on retry.
Idempotent via `Idempotency-Key` (same key returns the original result)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.ai_work import AIWorkLogCreate, AIWorkLogUpdate, AIWorkStatus
from studio_contracts.coordination import CoordinationEmit
from studio_contracts.handoff import HandoffRequest, HandoffResult
from studio_contracts.sync import SyncResult
from studio_contracts.tasks import TaskStatus

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import ai_work as ai_work_service
from studio_api.services import claims as claims_service
from studio_api.services import coordination as coordination_service
from studio_api.services import sessions as sessions_service
from studio_api.services import sync as sync_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_machine_owned,
    ensure_project_access,
)

# Stable namespace: the `coordination.handoff` event id derives from the
# session, so a replayed handoff never emits a second signal (C4).
_HANDOFF_SIGNAL_NAMESPACE = uuid.UUID("6f1c3a52-0d4e-4b7a-9c1e-5a2d8e7b3f10")


async def authorize_handoff(
    session: AsyncSession, principal: Principal, request: HandoffRequest
) -> None:
    """Project then role check, plus agent ownership when agent_id is
    provided. Run ahead of the idempotency replay short-circuit."""
    ensure_project_access(principal, request.project_id, "write")
    ensure_can_write(principal, "handoff")
    if request.agent_id is not None:
        agent = await session.get(AgentModel, request.agent_id)
        if agent is None or agent.machine_id != principal.machine.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "actor_not_owned",
                    "message": "agent_id must be an agent attached to the authenticated machine",
                },
            )


async def handoff(
    session: AsyncSession,
    principal: Principal,
    request: HandoffRequest,
) -> HandoffResult:
    """Run the composite handoff. Caller has already run authorization."""
    # Get the session
    work_session = await session.get(WorkSessionModel, request.session_id)
    if work_session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if work_session.task_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "invalid_session", "message": "session has no associated task"},
        )

    # Verify task belongs to project
    task = await tasks_service.get_task(session, work_session.task_id)
    if task is None or task.project_id != request.project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")

    # Verify session ownership
    ensure_machine_owned(principal, work_session.machine_id, "session", "end")

    # C4: last bounded sync, then the optional `coordination.handoff` signal,
    # both while the session is live and before the task can be closed (a
    # completed target refuses signals). The sync is acknowledged: the caller
    # receives it in this very response. A retry after the session already
    # ended skips both — the handoff cursor below converges on what was acked.
    last_sync: SyncResult | None = None
    coordination_event_id: uuid.UUID | None = None
    if work_session.ended_at is None:
        last_sync = await sync_service.sync(
            session,
            principal,
            session_id=request.session_id,
            ack=work_session.sync_cursor_seq,
        )
        await sessions_service.ack_sync_cursor(session, request.session_id, last_sync.next_cursor)
        if request.coordination is not None:
            emitted = await coordination_service.emit(
                session,
                principal,
                CoordinationEmit(
                    from_session_id=request.session_id,
                    intent="handoff",
                    task_id=task.id,
                    text=request.coordination.text,
                    refs=request.coordination.refs,
                    event_id=uuid.uuid5(_HANDOFF_SIGNAL_NAMESPACE, str(request.session_id)),
                ),
            )
            coordination_event_id = emitted.event_id
    elif request.coordination is not None:
        # Retry after a partial failure: recover the signal already emitted.
        signal_id = uuid.uuid5(_HANDOFF_SIGNAL_NAMESPACE, str(request.session_id))
        if await session.get(EventModel, signal_id) is not None:
            coordination_event_id = signal_id

    # Update task status if provided. A retry after a partial failure
    # converges instead of 409: when the version already moved but every
    # requested field is applied, the update is treated as done (DEC-0163).
    if request.task_status is not None:
        if request.expected_version is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error_code": "missing_expected_version",
                    "message": "expected_version is required when task_status is provided",
                },
            )
        task_update = request.task_status
        try:
            task = await tasks_service.update_task(
                session,
                principal,
                task,
                task_update,
                request.expected_version,
            )
        except HTTPException as exc:
            raw_detail = exc.detail
            detail: dict[str, Any] = raw_detail if isinstance(raw_detail, dict) else {}
            if (
                exc.status_code != status.HTTP_409_CONFLICT
                or detail.get("error_code") != "version_conflict"
            ):
                raise
            refreshed = await tasks_service.get_task(session, task.id)
            if refreshed is None:
                raise
            # Convergence compares every field of TaskUpdate (title,
            # description, status): keep this exhaustive if TaskUpdate grows,
            # otherwise a retry could silently swallow a new field (DEC-0163).
            if (
                (task_update.title is not None and refreshed.title != task_update.title)
                or (
                    task_update.description is not None
                    and refreshed.description != task_update.description
                )
                or (task_update.status is not None and refreshed.status != task_update.status.value)
            ):
                raise
            task = refreshed

    # Release all claims for the task
    released_claims = await claims_service.release_task_claims_by_task(session, principal, task)

    # Log AI work if agent_id provided. A retry converges: the entry already
    # logged for this (session, agent) pair is updated instead of duplicated,
    # so a pre-existing `started` entry receives the handoff's summary, final
    # status, files and tests instead of losing them. Earliest first:
    # deterministic (DEC-0163).
    ai_work_id = None
    if request.agent_id is not None and request.summary is not None:
        target_status = (
            request.ai_work_status if request.ai_work_status is not None else AIWorkStatus.COMPLETED
        )
        existing = (
            (
                await session.execute(
                    select(AIWorkLogModel)
                    .where(
                        AIWorkLogModel.session_id == request.session_id,
                        AIWorkLogModel.agent_id == request.agent_id,
                    )
                    .order_by(AIWorkLogModel.started_at)
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            updated = await ai_work_service.update_ai_work(
                session,
                principal,
                existing,
                AIWorkLogUpdate(
                    summary=request.summary,
                    status=target_status,
                    changed_files=request.changed_files,
                    tests_run=request.tests_run,
                ),
            )
            ai_work_id = updated.id
        else:
            ai_work = await ai_work_service.create_ai_work(
                session,
                principal,
                AIWorkLogCreate(
                    task_id=task.id,
                    project_id=request.project_id,
                    agent_id=request.agent_id,
                    machine_id=principal.machine.id,
                    session_id=request.session_id,
                    summary=request.summary,
                    status=target_status,
                    changed_files=request.changed_files or [],
                    tests_run=request.tests_run or [],
                ),
            )
            ai_work_id = ai_work.id

    # End the session
    await sessions_service.end_session(session, principal, request.session_id)

    # Advance the task's handoff cursor to the session's sync cursor (if any)
    if work_session.sync_cursor_seq is not None:
        task.handoff_cursor_seq = work_session.sync_cursor_seq
        await session.commit()

    return HandoffResult(
        task_id=task.id,
        task_status=TaskStatus(task.status),
        task_version=task.version,
        session_id=request.session_id,
        released_claims=[c.id for c in released_claims],
        ai_work_id=ai_work_id,
        sync=last_sync,
        handoff_cursor_seq=task.handoff_cursor_seq,
        coordination_event_id=coordination_event_id,
    )
