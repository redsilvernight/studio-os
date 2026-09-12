from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from studio_api.db.session import get_session_factory
from studio_api.services import events as events_service
from studio_contracts.events import EventCreate, EventType


async def studio_emit_event(
    project_id: str,
    event_type: str,
    actor_type: str,
    actor_id: str,
    task_id: str | None = None,
    machine_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit a Studio OS event (TECH/03_EVENT_CONTRACT.md). `event_type` must be
    one of the fixed EventType values (e.g. "task.started", "ai_work.completed")
    — an unknown value is rejected rather than silently accepted."""
    try:
        event_enum = EventType(event_type)
    except ValueError:
        return {
            "error_code": "invalid_event_type",
            "message": f"unknown event_type: {event_type!r}",
        }

    try:
        event_in = EventCreate(
            event_id=uuid4(),
            event_type=event_enum,
            project_id=UUID(project_id),
            task_id=UUID(task_id) if task_id else None,
            machine_id=UUID(machine_id) if machine_id else None,
            actor_type=actor_type,  # type: ignore[arg-type]
            actor_id=UUID(actor_id),
            client_timestamp=datetime.now(UTC),
            payload=payload or {},
        )
    except ValueError as exc:
        return {"error_code": "invalid_argument", "message": str(exc)}

    session_factory = get_session_factory()
    async with session_factory() as session:
        event = await events_service.create_event(session, event_in)
        return {
            "event_id": str(event.id),
            "event_type": event.event_type,
            "project_id": str(event.project_id),
            "server_timestamp": event.server_timestamp.isoformat(),
        }
