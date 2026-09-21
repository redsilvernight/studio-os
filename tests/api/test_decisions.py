from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel


async def _create_decision(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel, machine_id: uuid.UUID
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/decisions",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "title": "Use SSE for /stream",
            "body": "Server-Sent Events over WebSocket.",
            "proposed_by_type": "agent",
            "proposed_by_id": str(machine_id),
        },
    )
    assert response.status_code == 201
    return response.json()


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


async def test_accept_decision_transitions_proposed_to_accepted(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


async def test_accept_decision_twice_is_a_conflict(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)
    first = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "invalid_decision_transition"


async def test_supersede_decision_from_proposed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)

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
    decision = await _create_decision(client, auth_headers, project, machine_model.id)
    await client.post(f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers)

    response = await client.post(
        f"/api/v1/decisions/{decision['id']}/supersede", headers=admin_auth_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "superseded"


async def test_superseded_decision_is_terminal(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)
    await client.post(f"/api/v1/decisions/{decision['id']}/supersede", headers=admin_auth_headers)

    accept_after = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers
    )
    assert accept_after.status_code == 409

    supersede_again = await client.post(
        f"/api/v1/decisions/{decision['id']}/supersede", headers=admin_auth_headers
    )
    assert supersede_again.status_code == 409
    assert supersede_again.json()["detail"]["error_code"] == "invalid_decision_transition"


async def test_accept_global_decision_without_project_commits_without_an_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    """The event envelope requires `project_id` (`.claude/rules/contracts.md`),
    but a Decision's `project_id` is optional (a global decision) — the
    transition must still succeed, it just has nothing to publish."""
    machine_model, _ = machine
    response = await client.post(
        "/api/v1/decisions",
        headers=auth_headers,
        json={
            "project_id": None,
            "title": "Global decision",
            "body": "Body",
            "proposed_by_type": "agent",
            "proposed_by_id": str(machine_model.id),
        },
    )
    assert response.status_code == 201
    decision = response.json()
    assert decision["project_id"] is None

    accept = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers
    )
    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"


async def test_accept_decision_unknown_id_is_404(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"/api/v1/decisions/{uuid.uuid4()}/accept", headers=admin_auth_headers
    )
    assert response.status_code == 404


async def test_accept_decision_requires_admin(
    client: AsyncClient,
    auth_headers: dict[str, str],
    agent_auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)

    developer_attempt = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=auth_headers
    )
    assert developer_attempt.status_code == 403

    agent_attempt = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=agent_auth_headers
    )
    assert agent_attempt.status_code == 403

    readonly_attempt = await client.post(
        f"/api/v1/decisions/{decision['id']}/accept", headers=readonly_auth_headers
    )
    assert readonly_attempt.status_code == 403


async def test_accepted_decision_leaves_review_queue_but_proposed_stays(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    still_proposed = await _create_decision(client, auth_headers, project, machine_model.id)
    resolved = await _create_decision(client, auth_headers, project, machine_model.id)
    await client.post(f"/api/v1/decisions/{resolved['id']}/accept", headers=admin_auth_headers)

    queue = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    ids_in_queue = {
        item["id"] for item in queue.json()["items"] if item["kind"] == "decision_proposal"
    }
    assert still_proposed["id"] in ids_in_queue
    assert resolved["id"] not in ids_in_queue


async def test_accept_decision_emits_decision_accepted_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)
    await client.post(f"/api/v1/decisions/{decision['id']}/accept", headers=admin_auth_headers)

    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    matching = [
        e
        for e in events.json()
        if e["event_type"] == "decision.accepted"
        and e["payload"].get("decision_id") == decision["id"]
    ]
    assert len(matching) == 1
    assert matching[0]["payload"]["status"] == "accepted"


async def test_supersede_decision_emits_decision_superseded_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)
    await client.post(f"/api/v1/decisions/{decision['id']}/supersede", headers=admin_auth_headers)

    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    matching = [
        e
        for e in events.json()
        if e["event_type"] == "decision.superseded"
        and e["payload"].get("decision_id") == decision["id"]
    ]
    assert len(matching) == 1
