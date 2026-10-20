from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.work_session import WorkSessionModel


async def test_timeline_dates_and_pages_reach_history_before_500_events(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    old = datetime(2025, 1, 1, 12, tzinfo=UTC)
    recent = datetime(2026, 10, 20, 12, tzinfo=UTC)
    for index in range(506):
        stamp = old if index < 3 else recent
        db_session.add(
            EventModel(
                id=uuid.uuid4(),
                event_type="task.created",
                project_id=project.id,
                actor_type="system",
                actor_id=uuid.uuid4(),
                client_timestamp=stamp,
                server_timestamp=stamp,
                payload={"index": index},
            )
        )
    await db_session.flush()
    dates = await client.get(
        "/api/v1/timeline/dates", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert dates.status_code == 200
    assert dates.json() == ["2026-10-20", "2025-01-01"]
    query = {
        "project_id": str(project.id),
        "since": old.date().isoformat(),
        "until": (old + timedelta(days=1)).date().isoformat(),
        "limit": 2,
    }
    first = await client.get("/api/v1/timeline", headers=auth_headers, params=query)
    second = await client.get(
        "/api/v1/timeline", headers=auth_headers, params={**query, "offset": 2}
    )
    first_events = first.json()["days"][0]["events"]
    second_events = second.json()["days"][0]["events"]
    assert len(first_events) == 2
    assert len(second_events) == 1
    assert len({row["event_id"] for row in first_events + second_events}) == 3
    empty_page = await client.get(
        "/api/v1/timeline", headers=auth_headers, params={"project_id": str(project.id), "limit": 0}
    )
    assert empty_page.status_code == 200
    assert empty_page.json()["days"] == []


async def test_calendar_includes_sessions_without_events_and_pages_them(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    task = TaskModel(project_id=project.id, title="Historical task")
    db_session.add(task)
    await db_session.flush()
    start = datetime(2024, 2, 10, 23, tzinfo=UTC)
    end = start + timedelta(hours=2)
    for _ in range(3):
        db_session.add(
            WorkSessionModel(
                task_id=task.id, machine_id=machine[0].id, started_at=start, ended_at=end
            )
        )
    await db_session.flush()
    dates = await client.get(
        "/api/v1/timeline/dates", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert dates.status_code == 200
    assert dates.json() == ["2024-02-11", "2024-02-10"]
    query = {
        "project_id": str(project.id),
        "since": "2024-02-11T00:00:00Z",
        "until": "2024-02-12T00:00:00Z",
        "limit": 2,
    }
    first = await client.get("/api/v1/sessions", headers=auth_headers, params=query)
    second = await client.get(
        "/api/v1/sessions", headers=auth_headers, params={**query, "offset": 2}
    )
    assert first.status_code == second.status_code == 200
    rows = first.json() + second.json()
    assert len(first.json()) == 2
    assert len(second.json()) == 1
    assert len({row["id"] for row in rows}) == 3
    excluded = await client.get(
        "/api/v1/sessions", headers=auth_headers, params={**query, "since": "2024-02-12T00:00:00Z"}
    )
    assert excluded.json() == []
    all_sessions = await client.get(
        "/api/v1/sessions", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len(all_sessions.json()) == 3


@pytest.mark.isolation
async def test_history_project_authorization_and_pagination_validation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    unknown = str(uuid.uuid4())
    for route in ("/api/v1/timeline", "/api/v1/timeline/dates", "/api/v1/sessions"):
        response = await client.get(route, headers=auth_headers, params={"project_id": unknown})
        assert response.status_code == 403
        anonymous = await client.get(route, params={"project_id": str(project.id)})
        assert anonymous.status_code == 401
    for route in ("/api/v1/timeline", "/api/v1/sessions"):
        for invalid in ({"limit": 501}, {"offset": -1}):
            response = await client.get(
                route, headers=auth_headers, params={"project_id": str(project.id), **invalid}
            )
            assert response.status_code == 422
