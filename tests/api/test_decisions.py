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


async def _create_decision(
    client: AsyncClient,
    headers: dict[str, str],
    project: ProjectModel,
    machine_model: MachineModel,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/decisions",
        headers=headers,
        json={
            "project_id": str(project.id),
            "title": "Transition me",
            "body": "Body",
            "proposed_by_type": "agent",
            "proposed_by_id": str(machine_model.id),
        },
    )
    assert response.status_code == 201
    return response.json()


async def test_accept_decision_transitions_proposed_to_accepted(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model)

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["id"] == decision["id"]


async def test_accept_decision_requires_admin(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model)

    response = await client.post(f"/api/v1/decisions/{decision['id']}/accept", headers=auth_headers)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "forbidden"


async def test_accept_decision_rejects_readonly(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model)

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=readonly_auth_headers
    )

    assert response.status_code == 403


async def test_accept_decision_is_invalid_from_accepted(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model)
    await client.post(f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers)

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "invalid_status_transition"


async def test_accept_decision_unknown_id_is_404(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"/api/v1/decisions/{uuid.uuid4()}/accept", headers=admin_auth_headers
    )
    assert response.status_code == 404


async def test_supersede_decision_from_proposed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model)

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/supersede", headers=admin_auth_headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "superseded"


async def test_supersede_decision_from_accepted(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model)
    await client.post(f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers)

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/supersede", headers=admin_auth_headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "superseded"


async def test_supersede_decision_is_invalid_from_superseded(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model)
    await client.post(f"/api/v1/decisions/{decision['id']}/supersede", headers=admin_auth_headers)

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/supersede", headers=admin_auth_headers
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "invalid_status_transition"


async def test_supersede_decision_requires_admin(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model)

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/supersede", headers=auth_headers
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "forbidden"
