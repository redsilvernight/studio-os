"""`coordination.*` emission (C3, additive, DEC-0157): the single validated
write surface for structured inter-session signals.

The target is a task of the emitter's own project (optionally narrowed to
one live session of that task). Every signal is a plain event delivered
only through `studio_sync`; nothing here reads, pushes or reacts. Emission
is rate-limited per emitting session and idempotent on `event_id`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.coordination import (
    COORDINATION_EVENT_PREFIX,
    COORDINATION_PATH_MAX,
    COORDINATION_SESSION_LIMIT,
    CoordinationEmit,
    CoordinationEmitted,
)
from studio_contracts.events import EventCreate, EventType
from studio_contracts.tasks import TaskStatus

from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import events as events_service
from studio_api.services import sessions as sessions_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_machine_owned,
)


def _invalid(message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_coordination", "message": message},
    )


def _emitted(event: EventModel) -> CoordinationEmitted:
    target_session = (event.payload or {}).get("session_id")
    return CoordinationEmitted(
        event_id=event.id,
        event_type=event.event_type,
        seq=event.seq,
        task_id=event.task_id,  # type: ignore[arg-type]
        session_id=uuid.UUID(target_session) if target_session else None,
    )


async def emit(
    session: AsyncSession, principal: Principal, body: CoordinationEmit
) -> CoordinationEmitted:
    ensure_can_write(principal, "coordination")

    emitter = await session.get(WorkSessionModel, body.from_session_id)
    if emitter is None or emitter.ended_at is not None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "session_not_found",
                "message": "unknown or ended emitting session",
            },
        )
    emitter_task = await tasks_service.read_task(session, principal, emitter.task_id)
    if emitter_task is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "not_found", "message": "task not found"},
        )
    ensure_machine_owned(principal, emitter.machine_id, "session", "coordinate")
    project_id = emitter_task.project_id

    if body.event_id is not None:
        existing = await session.get(EventModel, body.event_id)
        if existing is not None:
            if (
                not existing.event_type.startswith(COORDINATION_EVENT_PREFIX)
                or existing.project_id != project_id
                or (existing.payload or {}).get("from_session_id") != str(emitter.id)
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "event_id_conflict",
                        "message": "event_id already used by another event",
                    },
                )
            return _emitted(existing)

    target = await tasks_service.read_task(session, principal, body.task_id)
    if target is None or target.project_id != project_id:
        raise _invalid("target task must exist in the emitting session's project")
    if target.status == TaskStatus.COMPLETED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "task_closed",
                "message": "target task is completed",
            },
        )

    if body.session_id is not None:
        target_session = await session.get(WorkSessionModel, body.session_id)
        if (
            target_session is None
            or target_session.ended_at is not None
            or target_session.task_id != target.id
        ):
            raise _invalid("session_id must be a live session of the target task")

    refs = body.refs
    if any(len(path) > COORDINATION_PATH_MAX or not path.strip() for path in refs.paths):
        raise _invalid(f"each path must be 1..{COORDINATION_PATH_MAX} characters")
    for ref_task_id in dict.fromkeys(refs.task_ids):
        ref_task = await tasks_service.read_task(session, principal, ref_task_id)
        if ref_task is None or ref_task.project_id != project_id:
            raise _invalid("every referenced task must exist in the same project")
    for ref_decision_id in dict.fromkeys(refs.decision_ids):
        ref_decision = await session.get(DecisionModel, ref_decision_id)
        if ref_decision is None or ref_decision.project_id != project_id:
            raise _invalid("every referenced decision must exist in the same project")

    if body.in_reply_to is not None:
        parent = await session.get(EventModel, body.in_reply_to)
        if (
            parent is None
            or parent.project_id != project_id
            or not parent.event_type.startswith(COORDINATION_EVENT_PREFIX)
        ):
            raise _invalid("in_reply_to must be a coordination signal of the same project")

    await session.refresh(emitter, with_for_update=True)
    if emitter.ended_at is not None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "session_not_found",
                "message": "unknown or ended emitting session",
            },
        )
    sent = await session.scalar(
        select(func.count())
        .select_from(EventModel)
        .where(
            EventModel.event_type.like(f"{COORDINATION_EVENT_PREFIX}%"),
            EventModel.payload["from_session_id"].astext == str(emitter.id),
        )
    )
    if (sent or 0) >= COORDINATION_SESSION_LIMIT:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "coordination_rate_limited",
                "message": f"at most {COORDINATION_SESSION_LIMIT} signals per session",
            },
        )

    machine = principal.machine
    if emitter.agent_id is not None:
        actor_type, actor_id = "agent", emitter.agent_id
    else:
        actor_type, actor_id = "system", machine.id
    payload: dict[str, object] = {
        "intent": body.intent,
        "task_id": str(target.id),
        "from_session_id": str(emitter.id),
        "text": body.text,
        "refs": {
            "task_ids": [str(t) for t in refs.task_ids],
            "decision_ids": [str(d) for d in refs.decision_ids],
            "paths": list(refs.paths),
        },
    }
    if body.session_id is not None:
        payload["session_id"] = str(body.session_id)
    if body.in_reply_to is not None:
        payload["in_reply_to"] = str(body.in_reply_to)

    event = await events_service.create_event(
        session,
        EventCreate(
            event_id=body.event_id or uuid.uuid4(),
            event_type=EventType(f"{COORDINATION_EVENT_PREFIX}{body.intent}"),
            project_id=project_id,
            task_id=target.id,
            machine_id=machine.id,
            actor_type=actor_type,  # type: ignore[arg-type]
            actor_id=actor_id,
            client_timestamp=datetime.now(UTC),
            payload=payload,
        ),
    )
    await sessions_service.touch_session(session, emitter.id)
    return _emitted(event)
