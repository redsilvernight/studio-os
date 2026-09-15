from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel

# UC-5 conformance: `agent_profile`, `harness`, `provider` and `model` are
# optional additive observability metadata on Agent and AIWorkLog. Open
# strings, any value accepted, never required, never an authorization or
# capability input (DEC-0043 amended, never read by authz.py).

UNKNOWN_RUNTIME = {
    "agent_profile": "fictional-role-that-does-not-exist",
    "harness": "unknown-harness",
    "provider": "unknown-provider",
    "model": "unknown-model",
}


async def test_agent_accepts_and_echoes_unknown_runtime_metadata(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    registered = await client.post(
        "/api/v1/agents",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"display_name": "probe", **UNKNOWN_RUNTIME},
    )
    assert registered.status_code == 201
    agent = registered.json()
    assert agent["machine_id"] == str(machine_model.id)
    for key, value in UNKNOWN_RUNTIME.items():
        assert agent[key] == value


async def test_agent_runtime_metadata_is_optional_and_defaults_to_null(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    registered = await client.post(
        "/api/v1/agents", headers=auth_headers, json={"display_name": "no-metadata"}
    )
    assert registered.status_code == 201
    for key in UNKNOWN_RUNTIME:
        assert registered.json()[key] is None


async def test_ai_work_accepts_and_echoes_runtime_metadata(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    agent = await client.post("/api/v1/agents", headers=auth_headers, json={"display_name": "w"})
    agent_id = agent.json()["id"]

    created = await client.post(
        "/api/v1/ai-work",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "agent_id": agent_id,
            "summary": "metadata probe",
            **UNKNOWN_RUNTIME,
        },
    )
    assert created.status_code == 201
    for key, value in UNKNOWN_RUNTIME.items():
        assert created.json()[key] == value

    listed = await client.get("/api/v1/ai-work", headers=auth_headers)
    assert listed.status_code == 200
    entry = next(item for item in listed.json() if item["id"] == created.json()["id"])
    for key, value in UNKNOWN_RUNTIME.items():
        assert entry[key] == value


async def test_runtime_metadata_does_not_change_authorization(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    """A consumer claiming a privileged-sounding profile/harness still gets
    exactly the rights of its `auth_role`: the metadata is never read by the
    authorization layer."""
    registered = await client.post(
        "/api/v1/agents",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "display_name": "privileged-looking",
            "agent_profile": "admin",
            "harness": "admin",
            "provider": "admin",
            "model": "admin",
        },
    )
    assert registered.status_code == 201

    readonly_agent = await client.post(
        "/api/v1/agents",
        headers=readonly_auth_headers,
        json={"display_name": "ro", "agent_profile": "admin"},
    )
    assert readonly_agent.status_code == 403
    assert readonly_agent.json()["detail"]["error_code"] == "forbidden"

    denied = await client.post(
        "/api/v1/tasks",
        headers=readonly_auth_headers,
        json={"project_id": str(project.id), "title": "still denied"},
    )
    assert denied.status_code == 403


async def test_runtime_metadata_does_not_alter_review_rules(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    """DEC-0041 holds regardless of any profile/harness value: the owning
    agent still cannot approve its own work."""
    agent_id = (
        await client.post("/api/v1/agents", headers=auth_headers, json={"display_name": "self"})
    ).json()["id"]
    work_id = (
        await client.post(
            "/api/v1/ai-work",
            headers=auth_headers,
            json={
                "project_id": str(project.id),
                "agent_id": agent_id,
                "summary": "review probe",
                **UNKNOWN_RUNTIME,
            },
        )
    ).json()["id"]

    requested = await client.patch(
        f"/api/v1/ai-work/{work_id}",
        headers=auth_headers,
        json={"status": "review_requested"},
    )
    assert requested.status_code == 200

    self_approved = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "approved"}
    )
    assert self_approved.status_code == 403
    assert self_approved.json()["detail"]["error_code"] == "forbidden"
