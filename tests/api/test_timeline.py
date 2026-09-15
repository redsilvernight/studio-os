from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.event import EventModel
from studio_api.db.models.project import ProjectModel


async def test_empty_timeline(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    response = await client.get(
        "/api/v1/timeline", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert response.status_code == 200
    assert response.json()["days"] == []


async def test_timeline_requires_project_id(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/timeline", headers=auth_headers)
    assert response.status_code == 422


async def test_timeline_groups_events_by_utc_calendar_day(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    day_one = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    day_two = datetime(2026, 9, 11, 3, 0, tzinfo=UTC)
    for offset, when in enumerate([day_one, day_one + timedelta(hours=2), day_two]):
        db_session.add(
            EventModel(
                id=uuid.uuid4(),
                event_type="task.created",
                project_id=project.id,
                actor_type="system",
                actor_id=uuid.uuid4(),
                client_timestamp=when,
                server_timestamp=when,
                payload={"seq": offset},
            )
        )
    await db_session.flush()

    response = await client.get(
        "/api/v1/timeline", headers=auth_headers, params={"project_id": str(project.id)}
    )
    days = response.json()["days"]
    assert len(days) == 2
    assert days[0]["date"] == "2026-09-11"
    assert days[1]["date"] == "2026-09-10"
    assert len(days[1]["events"]) == 2
    timestamps = [e["server_timestamp"] for e in days[1]["events"]]
    assert timestamps == sorted(timestamps)


async def test_timeline_respects_since_and_limit(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    since = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    response = await client.get(
        "/api/v1/timeline",
        headers=auth_headers,
        params={"project_id": str(project.id), "since": since, "limit": 1},
    )
    assert response.status_code == 200
    assert response.json()["days"] == []
