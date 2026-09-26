from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.events import EventEnvelope
from studio_contracts.timeline import Timeline, TimelineDay

from studio_api.services import events as events_service
from studio_api.services.authz import Principal


async def get_timeline(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    since: datetime | None = None,
    limit: int = 200,
) -> Timeline:
    """Groups `list_events` by UTC calendar date of `server_timestamp` —
    unfiltered, deliberately (DEC-0051): the notifications surface is the
    Review Queue (8.4), not this."""
    events = await events_service.list_events(
        session, principal, project_id=project_id, since=since, limit=limit
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
