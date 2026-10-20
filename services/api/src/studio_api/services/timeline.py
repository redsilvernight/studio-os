from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, cast, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.events import EventEnvelope
from studio_contracts.timeline import Timeline, TimelineDay

from studio_api.db.models.event import EventModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import events as events_service
from studio_api.services.authz import Principal, ensure_project_access


async def get_timeline(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    since: datetime | None = None,
    limit: int = 200,
    until: datetime | None = None,
    offset: int = 0,
) -> Timeline:
    """Groups `list_events` by UTC calendar date of `server_timestamp` —
    unfiltered, deliberately (DEC-0051): the notifications surface is the
    Review Queue (8.4), not this."""
    events = await events_service.list_events(
        session,
        principal,
        project_id=project_id,
        since=since,
        limit=limit,
        until=until,
        offset=offset,
    )
    by_day: dict[str, list[EventEnvelope]] = {}
    for event in events:
        day_key = event.server_timestamp.date().isoformat()
        by_day.setdefault(day_key, []).append(EventEnvelope.model_validate(event))

    days = [
        TimelineDay(
            date=datetime.fromisoformat(day_key).date(),
            events=sorted(day_events, key=lambda e: e.server_timestamp),
        )
        for day_key, day_events in by_day.items()
    ]
    days.sort(key=lambda d: d.date, reverse=True)
    return Timeline(project_id=project_id, days=days)


async def get_timeline_dates(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[date]:
    ensure_project_access(principal, project_id)
    events = select(
        cast(func.timezone("UTC", EventModel.server_timestamp), Date).label("day")
    ).where(EventModel.project_id == project_id)
    session_days = [
        select(cast(func.timezone("UTC", column), Date).label("day"))
        .join(TaskModel, WorkSessionModel.task_id == TaskModel.id)
        .where(TaskModel.project_id == project_id, column.is_not(None))
        for column in (WorkSessionModel.started_at, WorkSessionModel.ended_at)
    ]
    dates = union(events, *session_days).subquery()
    result = await session.execute(select(dates.c.day).order_by(dates.c.day.desc()))
    return list(result.scalars().all())
