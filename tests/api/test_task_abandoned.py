from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel


async def _task(client: AsyncClient, headers: dict[str, str], project: ProjectModel) -> dict:
    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"project_id": str(project.id), "title": "to abandon"},
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _patch_status(
    client: AsyncClient, headers: dict[str, str], task: dict, value: str
) -> object:
    return await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers={**headers, "If-Match-Version": str(task["version"])},
        json={"status": value},
    )


async def _active_ids(client: AsyncClient, headers: dict[str, str], project: ProjectModel) -> set:
    state = await client.get(f"/api/v1/projects/{project.id}/state", headers=headers)
    assert state.status_code == 200, state.text
    return {t["id"] for t in state.json()["active_tasks"]}


async def test_claimed_task_abandoned_leaves_active_list_and_claim(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    task = await _task(client, auth_headers, project)
    claimed = await client.post(f"/api/v1/tasks/{task['id']}/claim", headers=auth_headers)
    assert claimed.status_code == 200, claimed.text
    assert task["id"] in await _active_ids(client, auth_headers, project)

    abandoned = await _patch_status(client, auth_headers, claimed.json(), "abandoned")
    assert abandoned.status_code == 200, abandoned.text
    body = abandoned.json()
    assert body["status"] == "abandoned"
    assert body["claimed_by_machine_id"] is None
    assert task["id"] not in await _active_ids(client, auth_headers, project)

    stale = await _patch_status(client, auth_headers, claimed.json(), "abandoned")
    assert stale.status_code == 409
    assert stale.json()["detail"]["error_code"] == "version_conflict"

    reopened = await _patch_status(client, auth_headers, body, "created")
    assert reopened.status_code == 200, reopened.text
    assert task["id"] in await _active_ids(client, auth_headers, project)


async def test_completed_task_cannot_be_abandoned(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    task = await _task(client, auth_headers, project)
    done = await _patch_status(client, auth_headers, task, "completed")
    assert done.status_code == 200, done.text
    refused = await _patch_status(client, auth_headers, done.json(), "abandoned")
    assert refused.status_code == 409
    assert refused.json()["detail"]["error_code"] == "invalid_transition"


async def test_handoff_abandon_requires_reason(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    started = await client.post(
        "/api/v1/sessions",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"task_id": task["id"], "machine_id": str(machine[0].id)},
    )
    assert started.status_code == 201, started.text
    current = (await client.get(f"/api/v1/tasks/{task['id']}", headers=auth_headers)).json()
    payload = {
        "project_id": str(project.id),
        "session_id": started.json()["id"],
        "expected_version": current["version"],
        "task_status": {"status": "abandoned"},
    }
    missing = await client.post(
        "/api/v1/handoff",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json=payload,
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["error_code"] == "abandon_reason_required"

    handed = await client.post(
        "/api/v1/handoff",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={**payload, "summary": "obsolete: superseded by another task"},
    )
    assert handed.status_code == 200, handed.text
    final = (await client.get(f"/api/v1/tasks/{task['id']}", headers=auth_headers)).json()
    assert final["status"] == "abandoned"
    assert final["claimed_by_machine_id"] is None
