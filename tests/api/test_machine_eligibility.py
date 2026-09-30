from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_contracts.auth import HeartbeatRequest, MachineCapabilities


async def _task(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    project = await client.post(
        "/api/v1/projects",
        json={"slug": f"el-{uuid.uuid4().hex[:8]}", "name": "El"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    task = await client.post(
        "/api/v1/tasks", json={"project_id": project_id, "title": "t"}, headers=headers
    )
    assert task.status_code == 201, task.text
    return project_id, task.json()["id"]


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


def _caps(project_id: str, **overrides: Any) -> dict[str, Any]:
    caps: dict[str, Any] = {
        "harnesses": [{"harness_id": "claude-code", "version": "2.1.0"}],
        "project_ids": [project_id],
        "accepts_launches": True,
        "running_launches": 0,
        "max_launches": 2,
    }
    caps.update(overrides)
    return caps


async def _entry(
    client: AsyncClient, headers: dict[str, str], task_id: str, query: str = ""
) -> dict[str, Any]:
    response = await client.get(
        f"/api/v1/tasks/{task_id}/eligible-machines{query}", headers=headers
    )
    assert response.status_code == 200, response.text
    (entry,) = response.json()["machines"]
    return entry  # type: ignore[no-any-return]


async def test_eligible_when_every_condition_holds(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    model, _ = machine
    project_id, task_id = await _task(client, auth_headers)
    await _heartbeat(client, auth_headers, model.id, _caps(project_id))
    entry = await _entry(client, auth_headers, task_id, "?harness_id=claude-code")
    assert entry["eligible"] is True
    assert entry["reasons"] == []
    assert entry["free_slots"] == 2


async def test_no_report_is_not_eligible(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    model, _ = machine
    _, task_id = await _task(client, auth_headers)
    await _heartbeat(client, auth_headers, model.id, None)
    entry = await _entry(client, auth_headers, task_id)
    assert entry["eligible"] is False
    assert entry["reasons"] == ["no_capabilities_report"]


async def test_all_reasons_reported_in_fixed_order(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    model, _ = machine
    _, task_id = await _task(client, auth_headers)
    caps = _caps(str(uuid.uuid4()), accepts_launches=False, running_launches=2)
    await _heartbeat(client, auth_headers, model.id, caps)
    entry = await _entry(client, auth_headers, task_id, "?harness_id=codex")
    assert entry["reasons"] == [
        "project_not_registered",
        "launches_not_accepted",
        "harness_incompatible",
        "at_capacity",
    ]


async def test_heartbeat_without_capabilities_keeps_previous_report(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    model, _ = machine
    project_id, task_id = await _task(client, auth_headers)
    await _heartbeat(client, auth_headers, model.id, _caps(project_id))
    await _heartbeat(client, auth_headers, model.id, None)
    assert (await _entry(client, auth_headers, task_id))["eligible"] is True


async def test_stale_report_is_not_eligible(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id, task_id = await _task(client, auth_headers)
    await _heartbeat(client, auth_headers, model.id, _caps(project_id))
    model.capabilities_reported_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()
    entry = await _entry(client, auth_headers, task_id)
    assert entry["reasons"] == ["capabilities_stale"]


async def test_offline_machine_is_not_eligible(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id, task_id = await _task(client, auth_headers)
    await _heartbeat(client, auth_headers, model.id, _caps(project_id))
    model.last_seen_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()
    entry = await _entry(client, auth_headers, task_id)
    assert entry["status"] == "offline"
    assert "offline" in entry["reasons"]
    assert entry["eligible"] is False


async def test_unknown_task_is_404(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get(
        f"/api/v1/tasks/{uuid.uuid4()}/eligible-machines", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.parametrize("bad", ["C:\\Users\\me", "/home/me", "a b", "../x", "", "x" * 65])
def test_report_cannot_carry_a_path(bad: str) -> None:
    with pytest.raises(ValidationError):
        MachineCapabilities.model_validate({"harnesses": [{"harness_id": bad}]})
    with pytest.raises(ValidationError):
        MachineCapabilities.model_validate({"harnesses": [{"harness_id": "x", "version": bad}]})


def test_report_rejects_unknown_fields_and_negative_counts() -> None:
    with pytest.raises(ValidationError):
        MachineCapabilities.model_validate({"hostname": "box"})
    with pytest.raises(ValidationError):
        MachineCapabilities.model_validate({"running_launches": -1})


def test_heartbeat_capabilities_is_optional() -> None:
    request = HeartbeatRequest(machine_id=uuid.uuid4(), client_timestamp=datetime.now(UTC))
    assert request.capabilities is None
