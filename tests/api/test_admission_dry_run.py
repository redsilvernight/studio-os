"""HTTP acceptance of the read-only roadmap admission dry-run (Mission Control
P05, additive).

Real Postgres through the shared savepoint fixtures. Covers: the endpoint is a
pure read (no `TaskLaunch` created), 403/404, dependency exclusion, a step with
no linked task, an expired claim never excluding, and the stability of
`plan_digest` across two identical calls.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel

Headers = dict[str, str]

DOCUMENT: dict[str, Any] = {
    "format": "studio.roadmap/v1",
    "title": "Plan",
    "phases": [
        {
            "key": "P1",
            "title": "Phase one",
            "steps": [
                {"key": "S1", "title": "Step one"},
                {"key": "S2", "title": "Step two", "depends_on": ["S1"]},
            ],
        }
    ],
}


async def _project(client: AsyncClient, headers: Headers) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={"slug": f"adm-{uuid.uuid4().hex[:8]}", "name": "Adm"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]  # type: ignore[no-any-return]


async def _task(client: AsyncClient, headers: Headers, project_id: str) -> str:
    response = await client.post(
        "/api/v1/tasks", json={"project_id": project_id, "title": "T"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]  # type: ignore[no-any-return]


async def _active_roadmap(
    client: AsyncClient, headers: Headers, project_id: str, doc: dict[str, Any] | None = None
) -> dict[str, Any]:
    created = await client.post(
        "/api/v1/roadmaps/import",
        headers=headers,
        json={"project_id": project_id, "document": doc or DOCUMENT},
    )
    assert created.status_code == 201, created.text
    roadmap = created.json()
    activated = await client.post(
        f"/api/v1/roadmaps/{roadmap['id']}/transitions",
        headers=headers,
        json={"transition": "activate", "expected_version": roadmap["version"]},
    )
    assert activated.status_code == 200, activated.text
    return activated.json()  # type: ignore[no-any-return]


async def _link(
    client: AsyncClient, headers: Headers, roadmap_id: str, step_key: str, task_id: str
) -> None:
    response = await client.post(
        f"/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/links",
        headers=headers,
        json={"task_id": task_id},
    )
    assert response.status_code == 201, response.text


async def _heartbeat(
    client: AsyncClient, headers: Headers, machine_id: uuid.UUID, project_id: str
) -> None:
    response = await client.post(
        "/api/v1/heartbeats",
        headers=headers,
        json={
            "machine_id": str(machine_id),
            "client_timestamp": datetime.now(UTC).isoformat(),
            "capabilities": {
                "harnesses": [
                    {
                        "harness_id": "claude-code",
                        "version": "2.1.0",
                        "detected": True,
                        "configured": True,
                    }
                ],
                "project_ids": [project_id],
                "accepts_launches": True,
                "launch_safety": True,
                "running_launches": 0,
                "max_launches": 2,
            },
        },
    )
    assert response.status_code == 200, response.text


async def _dry_run(
    client: AsyncClient, headers: Headers, roadmap_id: str, query: str = ""
) -> dict[str, Any]:
    response = await client.get(
        f"/api/v1/roadmaps/{roadmap_id}/admission/dry-run{query}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _exclusion(body: dict[str, Any], task_id: str) -> dict[str, Any]:
    return next(item for item in body["excluded"] if item["task_id"] == task_id)


async def _launch_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(TaskLaunchModel))).scalar_one()


async def test_dry_run_creates_no_task_launch(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    task_id = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", task_id)
    await _heartbeat(client, auth_headers, model.id, project_id)

    before = await _launch_count(db_session)
    body = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")
    after = await _launch_count(db_session)

    assert after == before
    assert [item["task_id"] for item in body["launchable"]] == [task_id]
    assert body["excluded"] == []


async def test_unknown_roadmap_is_404(client: AsyncClient, auth_headers: Headers) -> None:
    response = await client.get(
        f"/api/v1/roadmaps/{uuid.uuid4()}/admission/dry-run", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "not_found"


@pytest.mark.isolation
async def test_inaccessible_project_is_403(
    client: AsyncClient, auth_headers: Headers, other_auth_headers: Headers
) -> None:
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    response = await client.get(
        f"/api/v1/roadmaps/{roadmap['id']}/admission/dry-run", headers=other_auth_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "forbidden"


async def test_pending_dependency_excludes_task(client: AsyncClient, auth_headers: Headers) -> None:
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    first = await _task(client, auth_headers, project_id)
    second = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", first)
    await _link(client, auth_headers, roadmap["id"], "S2", second)

    body = await _dry_run(client, auth_headers, roadmap["id"])
    exclusion = _exclusion(body, second)
    assert "dependency_pending" in exclusion["reasons"]
    assert exclusion["waiting_on"] == ["S1"]


async def test_step_without_task_is_reported(client: AsyncClient, auth_headers: Headers) -> None:
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)

    body = await _dry_run(client, auth_headers, roadmap["id"])
    assert set(body["steps_without_tasks"]) == {"S1", "S2"}
    assert body["launchable"] == []


async def test_expired_claim_does_not_exclude(
    client: AsyncClient,
    auth_headers: Headers,
    other_auth_headers: Headers,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    task_id = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", task_id)
    await _heartbeat(client, auth_headers, model.id, project_id)
    claim = await client.post(
        "/api/v1/claims",
        headers=other_auth_headers,
        json={
            "project_id": project_id,
            "task_id": task_id,
            "resource_path": "src/x.py",
            "resource_type": "file",
            "ttl_seconds": 60,
        },
    )
    assert claim.status_code == 201, claim.text

    active = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")
    assert "claims_held_elsewhere" in _exclusion(active, task_id)["reasons"]

    row = (
        await db_session.execute(
            select(ResourceClaimModel).where(ResourceClaimModel.task_id == uuid.UUID(task_id))
        )
    ).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    expired = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")
    assert [item["task_id"] for item in expired["launchable"]] == [task_id]


async def test_two_calls_share_plan_digest(client: AsyncClient, auth_headers: Headers) -> None:
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)

    first = await _dry_run(client, auth_headers, roadmap["id"])
    second = await _dry_run(client, auth_headers, roadmap["id"])
    assert first["plan_digest"] == second["plan_digest"]
