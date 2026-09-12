from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from studio_contracts.events import EventCreate, EventEnvelope

from studio_api.deps import CurrentMachine, DbSession
from studio_api.services import events as events_service

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post("", response_model=EventEnvelope)
async def post_event(
    event_in: EventCreate, machine: CurrentMachine, session: DbSession
) -> EventEnvelope:
    event = await events_service.create_event(session, event_in)
    return EventEnvelope.model_validate(event)


@router.get("", response_model=list[EventEnvelope])
async def get_events(
    session: DbSession,
    machine: CurrentMachine,
    project: UUID | None = Query(default=None),
    task: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[EventEnvelope]:
    events = await events_service.list_events(
        session,
        project_id=str(project) if project else None,
        task_id=str(task) if task else None,
        since=since,
        limit=limit,
    )
    return [EventEnvelope.model_validate(e) for e in events]
