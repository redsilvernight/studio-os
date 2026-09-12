from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel


def _event_payload(
    project_id: uuid.UUID, actor_id: uuid.UUID, event_id: uuid.UUID
) -> dict[str, object]:
    return {
        "event_id": str(event_id),
        "event_type": "task.created",
        "project_id": str(project_id),
        "actor_type": "system",
        "actor_id": str(actor_id),
        "client_timestamp": datetime.now(UTC).isoformat(),
        "payload": {"title": "Some task"},
    }


async def test_event_replay_by_event_id_returns_original_row(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    event_id = uuid.uuid4()
    payload = _event_payload(project.id, machine_model.id, event_id)

    first = await client.post("/api/v1/events", headers=auth_headers, json=payload)
    assert first.status_code == 200
    first_body = first.json()

    replay_payload = dict(payload)
    replay_payload["payload"] = {"title": "Different, ignored on replay"}
    second = await client.post("/api/v1/events", headers=auth_headers, json=replay_payload)
    assert second.status_code == 200
    second_body = second.json()

    assert second_body["event_id"] == first_body["event_id"]
    assert second_body["server_timestamp"] == first_body["server_timestamp"]
    assert second_body["payload"] == {"title": "Some task"}

    listing = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    matching = [e for e in listing.json() if e["event_id"] == str(event_id)]
    assert len(matching) == 1


async def test_get_events_filters_by_project(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await client.post(
        "/api/v1/events",
        headers=auth_headers,
        json=_event_payload(project.id, machine_model.id, uuid.uuid4()),
    )

    other_project_events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(uuid.uuid4())}
    )
    assert other_project_events.json() == []

    same_project_events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    assert len(same_project_events.json()) == 1
