from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.events import EventCreate

from studio_api.db.models.event import EventModel


async def create_event(session: AsyncSession, event_in: EventCreate) -> EventModel:
    """Idempotent on `event_id`: a replay (offline queue retry, at-least-once
    delivery) returns the already-stored row instead of inserting a duplicate."""
    existing = await session.get(EventModel, event_in.event_id)
    if existing is not None:
        return existing

    event = EventModel(
        id=event_in.event_id,
        event_type=event_in.event_type.value,
        project_id=event_in.project_id,
        task_id=event_in.task_id,
        machine_id=event_in.machine_id,
        actor_type=event_in.actor_type,
        actor_id=event_in.actor_id,
        client_timestamp=event_in.client_timestamp,
        server_timestamp=datetime.now(UTC),
        payload=event_in.payload,
        schema_version=event_in.schema_version,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def list_events(
    session: AsyncSession,
    project_id: str | None = None,
    task_id: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[EventModel]:
    stmt = select(EventModel).order_by(EventModel.server_timestamp.desc()).limit(limit)
    if project_id is not None:
        stmt = stmt.where(EventModel.project_id == project_id)
    if task_id is not None:
        stmt = stmt.where(EventModel.task_id == task_id)
    if since is not None:
        stmt = stmt.where(EventModel.server_timestamp >= since)
    result = await session.execute(stmt)
    return list(result.scalars().all())
