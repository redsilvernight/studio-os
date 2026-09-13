from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.services import events as events_service
from studio_contracts.events import EventCreate, EventType

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_event(event: EventModel) -> dict[str, Any]:
    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "project_id": str(event.project_id),
        "task_id": str(event.task_id) if event.task_id else None,
        "actor_type": event.actor_type,
        "actor_id": str(event.actor_id),
        "server_timestamp": event.server_timestamp.isoformat(),
        "payload": event.payload,
    }


async def studio_emit_event(
    project_id: str,
    event_type: str,
    actor_type: str,
    actor_id: str,
    ctx: Context,
    task_id: str | None = None,
    machine_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit a Studio OS event (task/session/claim/decision/ai_work/... lifecycle)
    so other agents and the dashboard see it. event_type must match
    TECH/03_EVENT_CONTRACT.md (e.g. 'task.started')."""

    async def _handler(session: AsyncSession, machine: MachineModel) -> dict[str, Any]:
        try:
            event_enum = EventType(event_type)
        except ValueError:
            return {
                "error_code": "invalid_event_type",
                "message": f"unknown event_type: {event_type!r}",
            }

        parsed_project_id = parse_uuid(project_id, "project_id")
        if isinstance(parsed_project_id, dict):
            return parsed_project_id
        parsed_actor_id = parse_uuid(actor_id, "actor_id")
        if isinstance(parsed_actor_id, dict):
            return parsed_actor_id
        parsed_task_id = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task_id = parsed
        parsed_machine_id = None
        if machine_id is not None:
            parsed = parse_uuid(machine_id, "machine_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_machine_id = parsed

        try:
            event_in = EventCreate(
                event_id=uuid4(),
                event_type=event_enum,
                project_id=parsed_project_id,
                task_id=parsed_task_id,
                machine_id=parsed_machine_id if parsed_machine_id else machine.id,
                actor_type=actor_type,  # type: ignore[arg-type]
                actor_id=parsed_actor_id,
                client_timestamp=datetime.now(UTC),
                payload=payload or {},
            )
        except ValueError as exc:
            return {"error_code": "invalid_argument", "message": str(exc)}

        event = await events_service.create_event(session, event_in)
        return _compact_event(event)

    return await run_tool(ctx, _handler)


async def studio_get_recent_changes(
    ctx: Context,
    project_id: str | None = None,
    task_id: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List recent events, optionally filtered by project_id/task_id (UUID
    strings) and `since` (ISO-8601 timestamp)."""

    async def _handler(session: AsyncSession, _machine: MachineModel) -> dict[str, Any]:
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = str(parsed)
        parsed_task_id = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task_id = str(parsed)
        parsed_since = None
        if since is not None:
            try:
                parsed_since = datetime.fromisoformat(since)
            except ValueError:
                return {
                    "error_code": "invalid_argument",
                    "message": f"since is not ISO-8601: {since!r}",
                }
        events = await events_service.list_events(
            session,
            project_id=parsed_project_id,
            task_id=parsed_task_id,
            since=parsed_since,
            limit=limit,
        )
        return {"events": [_compact_event(e) for e in events]}

    return await run_tool(ctx, _handler)
