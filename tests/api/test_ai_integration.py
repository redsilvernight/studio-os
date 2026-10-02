from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={"slug": f"ai-{uuid.uuid4().hex[:8]}", "name": "Ai"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _heartbeat(
    client: AsyncClient,
    headers: dict[str, str],
    machine_id: uuid.UUID,
    capabilities: dict[str, Any] | None,
) -> None:
    body: dict[str, Any] = {
        "machine_id": str(machine_id),
        "client_timestamp": datetime.now(UTC).isoformat(),
    }
    if capabilities is not None:
        body["capabilities"] = capabilities
    response = await client.post("/api/v1/heartbeats", headers=headers, json=body)
    assert response.status_code == 200, response.text


async def _status(client: AsyncClient, headers: dict[str, str], project_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/projects/{project_id}/ai-integration", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_never_reported_machine_is_not_presented_as_configured(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    body = await _status(client, auth_headers, project_id)
    (entry,) = [m for m in body["machines"] if m["machine_id"] == str(model.id)]
    assert entry["freshness"] == "never_reported"
    assert "reported_at" not in entry
    assert "project_registered" not in entry
    assert entry["harnesses"] == []


async def test_reported_state_is_the_machine_claim(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    await _heartbeat(
        client,
        auth_headers,
        model.id,
        {
            "harnesses": [{"harness_id": "claude-code", "detected": True, "configured": False}],
            "project_ids": [project_id],
        },
    )
    body = await _status(client, auth_headers, project_id)
    (entry,) = [m for m in body["machines"] if m["machine_id"] == str(model.id)]
    assert entry["freshness"] == "fresh"
    assert entry["project_registered"] is True
    assert entry["harnesses"] == [
        {"harness_id": "claude-code", "detected": True, "configured": False}
    ]
    assert entry["reported_at"]


async def test_unregistered_project_and_stale_report(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    await _heartbeat(client, auth_headers, model.id, {"project_ids": [str(uuid.uuid4())]})
    model.capabilities_reported_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()
    body = await _status(client, auth_headers, project_id)
    (entry,) = [m for m in body["machines"] if m["machine_id"] == str(model.id)]
    assert entry["freshness"] == "stale"
    assert entry["project_registered"] is False


async def test_desired_plan_summary_or_public_error(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await _project(client, auth_headers)
    body = await _status(client, auth_headers, project_id)
    if body.get("desired") is not None:
        assert len(body["desired"]["plan_hash"]) == 64
        assert "desired_error" not in body
    else:
        assert isinstance(body["desired_error"], str)


async def test_applied_bootstrap_is_the_machine_observation(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    other = str(uuid.uuid4())
    checked_at = datetime.now(UTC).isoformat()

    def _status_entry(pid: str, **counts: int) -> dict[str, Any]:
        return {"project_id": pid, "checked_at": checked_at, "summary": counts}

    await _heartbeat(
        client,
        auth_headers,
        model.id,
        {"bootstrap": [_status_entry(other, up_to_date=3)]},
    )
    body = await _status(client, auth_headers, project_id)
    (entry,) = [m for m in body["machines"] if m["machine_id"] == str(model.id)]
    assert "bootstrap" not in entry

    await _heartbeat(
        client,
        auth_headers,
        model.id,
        {"bootstrap": [_status_entry(project_id, up_to_date=3, modified=1)]},
    )
    body = await _status(client, auth_headers, project_id)
    (entry,) = [m for m in body["machines"] if m["machine_id"] == str(model.id)]
    assert entry["bootstrap"]["in_sync"] is False
    assert entry["bootstrap"]["summary"]["modified"] == 1

    await _heartbeat(
        client, auth_headers, model.id, {"bootstrap": [_status_entry(project_id, up_to_date=4)]}
    )
    body = await _status(client, auth_headers, project_id)
    (entry,) = [m for m in body["machines"] if m["machine_id"] == str(model.id)]
    assert entry["bootstrap"]["in_sync"] is True


async def test_foreign_stored_capabilities_do_not_break_ai_integration(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    model.capabilities = {"os": "linux", "arch": "x64", "tools": ["docker"]}
    model.capabilities_reported_at = datetime.now(UTC)
    await db_session.commit()
    body = await _status(client, auth_headers, project_id)
    (entry,) = [m for m in body["machines"] if m["machine_id"] == str(model.id)]
    assert entry["freshness"] == "never_reported"
    assert entry["harnesses"] == []
