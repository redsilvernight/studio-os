from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel


async def test_create_and_list_decision(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    response = await client.post(
        "/api/v1/decisions",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "title": "Use SSE for /stream",
            "body": "Server-Sent Events over WebSocket — see DEC-0008.",
            "proposed_by_type": "agent",
            "proposed_by_id": str(machine_model.id),
        },
    )
    assert response.status_code == 201
    decision = response.json()
    assert decision["status"] == "proposed"

    listing = await client.get(
        "/api/v1/decisions", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len(listing.json()) == 1


async def test_create_decision_idempotency_key_replays(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    payload = {
        "project_id": str(project.id),
        "title": "Repeated decision",
        "body": "Body",
        "proposed_by_type": "agent",
        "proposed_by_id": str(machine_model.id),
    }

    first = await client.post("/api/v1/decisions", headers=headers, json=payload)
    second = await client.post("/api/v1/decisions", headers=headers, json=payload)

    assert first.json()["id"] == second.json()["id"]

    listing = await client.get(
        "/api/v1/decisions", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len(listing.json()) == 1
