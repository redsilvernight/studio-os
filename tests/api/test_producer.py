from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel


async def _create_task(
    client: AsyncClient, auth_headers: dict[str, str], project_id: uuid.UUID, title: str
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project_id), "title": title},
    )
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body, dict)
    return body


async def _setup_tasks(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> dict[str, dict[str, object]]:
    waiting = await _create_task(client, auth_headers, project.id, "Waiting")
    active = await _create_task(client, auth_headers, project.id, "Active")
    blocked = await _create_task(client, auth_headers, project.id, "Blocked")
    done = await _create_task(client, auth_headers, project.id, "Done")

    claim = await client.post(f"/api/v1/tasks/{active['id']}/claim", headers=auth_headers, json={})
    assert claim.status_code == 200

    version = int(blocked["version"]) if "version" in blocked else 1
    patch = await client.patch(
        f"/api/v1/tasks/{blocked['id']}",
        headers={**auth_headers, "If-Match-Version": str(version)},
        json={"status": "blocked"},
    )
    assert patch.status_code == 200

    version = int(done["version"]) if "version" in done else 1
    patch = await client.patch(
        f"/api/v1/tasks/{done['id']}",
        headers={**auth_headers, "If-Match-Version": str(version)},
        json={"status": "completed"},
    )
    assert patch.status_code == 200
    return {"waiting": waiting, "active": active, "blocked": blocked, "done": done}


async def test_priority_analysis_orders_and_excludes_completed(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    tasks = await _setup_tasks(client, auth_headers, project)
    response = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={"project_id": str(project.id), "kind": "priority_analysis"},
    )
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "completed"
    ranking = job["result"]["ranking"]
    ids = [entry["task_id"] for entry in ranking]
    assert ids == [tasks["active"]["id"], tasks["waiting"]["id"], tasks["blocked"]["id"]]
    assert tasks["done"]["id"] not in ids


async def test_blocker_detection_lists_blocked_task_and_claim_conflict(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    tasks = await _setup_tasks(client, auth_headers, project)
    for headers in (auth_headers, other_auth_headers):
        response = await client.post(
            "/api/v1/claims",
            headers=headers,
            json={
                "project_id": str(project.id),
                "resource_path": "src/shared.py",
                "resource_type": "file",
                "ttl_seconds": 600,
            },
        )
        assert response.status_code == 201
    response = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={"project_id": str(project.id), "kind": "blocker_detection"},
    )
    assert response.status_code == 201
    blockers = response.json()["result"]["blockers"]
    reasons = {blocker["reason"] for blocker in blockers}
    assert "task status is blocked" in reasons
    assert "conflicting active claims on overlapping paths" in reasons
    assert any(
        blocker.get("task_id") == tasks["blocked"]["id"]
        for blocker in blockers
        if "task_id" in blocker
    )


async def test_parallelization_groups_disjoint_claims(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    first = await _create_task(client, auth_headers, project.id, "First")
    second = await _create_task(client, auth_headers, project.id, "Second")
    third = await _create_task(client, auth_headers, project.id, "Third")
    await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "task_id": first["id"],
            "resource_path": "src/a.py",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "task_id": second["id"],
            "resource_path": "src/b.py",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "task_id": third["id"],
            "resource_path": "src",
            "resource_type": "folder",
            "ttl_seconds": 600,
        },
    )
    response = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={"project_id": str(project.id), "kind": "parallelization"},
    )
    assert response.status_code == 201
    groups = response.json()["result"]["groups"]
    flat = [[member["task_id"] for member in group] for group in groups]
    assert {first["id"], second["id"]} in [set(group) for group in flat] or any(
        first["id"] in group and second["id"] in group for group in flat
    )
    assert not any(third["id"] in group and first["id"] in group for group in flat)


async def test_decomposition_proposes_bullets_and_writes_nothing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    task = await _create_task(client, auth_headers, project.id, "Decompose me")
    version = int(task["version"]) if "version" in task else 1
    await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers={**auth_headers, "If-Match-Version": str(version)},
        json={"description": "- design HUD\n- implement HUD\n- test HUD"},
    )
    tasks_before = (
        await db_session.execute(select(func.count()).select_from(TaskModel))
    ).scalar_one()
    response = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "kind": "decomposition",
            "task_id": task["id"],
        },
    )
    assert response.status_code == 201
    proposed = response.json()["result"]["proposed_subtasks"]
    assert [item["title"] for item in proposed] == ["design HUD", "implement HUD", "test HUD"]
    tasks_after = (
        await db_session.execute(select(func.count()).select_from(TaskModel))
    ).scalar_one()
    assert tasks_after == tasks_before


async def test_decomposition_without_structure_proposes_nothing(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    task = await _create_task(client, auth_headers, project.id, "Vague")
    response = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "kind": "decomposition",
            "task_id": task["id"],
        },
    )
    assert response.status_code == 201
    assert response.json()["result"]["proposed_subtasks"] == []
    assert "note" in response.json()["result"]


async def test_producer_emits_job_events(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={"project_id": str(project.id), "kind": "priority_analysis"},
    )
    types = (
        (
            await db_session.execute(
                select(EventModel.event_type).where(EventModel.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert "producer.job.requested" in types
    assert "producer.job.completed" in types


async def test_producer_rejects_unknown_project_task_and_role(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    unknown_project = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={"project_id": str(uuid.uuid4()), "kind": "priority_analysis"},
    )
    assert unknown_project.status_code == 404

    unknown_task = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "kind": "decomposition",
            "task_id": str(uuid.uuid4()),
        },
    )
    assert unknown_task.status_code == 404

    readonly = await client.post(
        "/api/v1/producer-jobs",
        headers=readonly_auth_headers,
        json={"project_id": str(project.id), "kind": "priority_analysis"},
    )
    assert readonly.status_code == 403

    invalid_kind = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={"project_id": str(project.id), "kind": "telepathy"},
    )
    assert invalid_kind.status_code == 422


async def test_decomposition_requires_task_id(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    response = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={"project_id": str(project.id), "kind": "decomposition"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "task_required"


async def test_producer_replay_returns_same_job(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    headers = {**auth_headers, "Idempotency-Key": f"producer-{uuid.uuid4().hex}"}
    body = {"project_id": str(project.id), "kind": "blocker_detection"}
    first = await client.post("/api/v1/producer-jobs", headers=headers, json=body)
    second = await client.post("/api/v1/producer-jobs", headers=headers, json=body)
    assert first.status_code == 201
    assert second.json()["id"] == first.json()["id"]


async def test_producer_jobs_list_and_get(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    assert machine is not None
    created = await client.post(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        json={"project_id": str(project.id), "kind": "priority_analysis"},
    )
    job_id = created.json()["id"]
    listed = await client.get(
        "/api/v1/producer-jobs",
        headers=auth_headers,
        params={"project_id": str(project.id)},
    )
    assert listed.status_code == 200
    assert [job["id"] for job in listed.json()] == [job_id]
    fetched = await client.get(f"/api/v1/producer-jobs/{job_id}", headers=auth_headers)
    assert fetched.status_code == 200
    missing = await client.get(f"/api/v1/producer-jobs/{uuid.uuid4()}", headers=auth_headers)
    assert missing.status_code == 404
