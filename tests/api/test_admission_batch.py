"""HTTP acceptance of `POST /api/v1/roadmaps/{roadmap_id}/admission` (Mission
Control P05, additive).

Real Postgres through the shared savepoint fixtures. Covers: admitting two
Tasks in one transaction, `admission_plan_changed` when the plan moved, every
per-item refusal (`duplicate_item`, `not_launchable` + `exclusion_reasons`,
`machine_not_eligible`, `budget_refused`) with a full rollback (no
`TaskLaunch`, no reservation), the replay of the same `Idempotency-Key`, and an
approved `enforce` budget that exhausts its slots.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.budget import BudgetReservationModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel

Headers = dict[str, str]

INDEPENDENT: dict[str, Any] = {
    "format": "studio.roadmap/v1",
    "title": "Plan",
    "phases": [
        {
            "key": "P1",
            "title": "Phase one",
            "steps": [
                {"key": "S1", "title": "Step one"},
                {"key": "S2", "title": "Step two"},
            ],
        }
    ],
}

DEPENDENT: dict[str, Any] = {
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
        json={"slug": f"adb-{uuid.uuid4().hex[:8]}", "name": "Adb"},
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
        json={"project_id": project_id, "document": doc or INDEPENDENT},
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


def _batch(plan_digest: str, items: list[tuple[str, str]], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "plan_digest": plan_digest,
        "harness_id": "claude-code",
        "items": [{"task_id": task, "machine_id": machine} for task, machine in items],
    }
    body.update(overrides)
    return body


async def _admit(
    client: AsyncClient,
    headers: Headers,
    roadmap_id: str,
    body: dict[str, Any],
    key: str | None = None,
) -> Any:
    extra = {"Idempotency-Key": key} if key else {}
    return await client.post(
        f"/api/v1/roadmaps/{roadmap_id}/admission",
        json=body,
        headers={**headers, **extra},
    )


async def _launch_count(session: AsyncSession, project_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(TaskLaunchModel)
            .where(TaskLaunchModel.project_id == uuid.UUID(project_id))
        )
        or 0
    )


async def _reservation_count(session: AsyncSession, project_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(BudgetReservationModel)
            .where(BudgetReservationModel.project_id == uuid.UUID(project_id))
        )
        or 0
    )


async def _requested_events(
    client: AsyncClient, headers: Headers, project_id: str
) -> list[dict[str, Any]]:
    response = await client.get(
        "/api/v1/events", params={"project": project_id, "limit": 500}, headers=headers
    )
    assert response.status_code == 200, response.text
    return [e for e in response.json() if e["event_type"] == "task_launch.requested"]


def _reason(body: dict[str, Any], reason: str) -> dict[str, Any]:
    return next(refusal for refusal in body["refusals"] if refusal["reason"] == reason)


async def test_admit_batch_creates_one_launch_per_item(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    first = await _task(client, auth_headers, project_id)
    second = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", first)
    await _link(client, auth_headers, roadmap["id"], "S2", second)
    await _heartbeat(client, auth_headers, model.id, project_id)

    plan = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")
    assert {c["task_id"] for c in plan["launchable"]} == {first, second}

    response = await _admit(
        client,
        auth_headers,
        roadmap["id"],
        _batch(plan["plan_digest"], [(first, str(model.id)), (second, str(model.id))]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["roadmap_id"] == roadmap["id"]
    assert body["plan_digest"] == plan["plan_digest"]
    assert {launch["task_id"] for launch in body["launches"]} == {first, second}
    assert all(launch["status"] == "requested" for launch in body["launches"])
    assert await _launch_count(db_session, project_id) == 2
    assert len(await _requested_events(client, auth_headers, project_id)) == 2


async def test_plan_changed_is_409_and_creates_nothing(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    first = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", first)
    await _heartbeat(client, auth_headers, model.id, project_id)
    plan = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")

    later = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S2", later)

    response = await _admit(
        client, auth_headers, roadmap["id"], _batch(plan["plan_digest"], [(first, str(model.id))])
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "admission_plan_changed"
    assert detail["plan"]["plan_digest"] != plan["plan_digest"]
    assert detail["refusals"] == []
    assert await _launch_count(db_session, project_id) == 0


async def test_duplicate_item_refused_with_rollback(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    task = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", task)
    await _heartbeat(client, auth_headers, model.id, project_id)
    plan = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")

    response = await _admit(
        client,
        auth_headers,
        roadmap["id"],
        _batch(plan["plan_digest"], [(task, str(model.id)), (task, str(model.id))]),
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "admission_refused"
    assert _reason(detail, "duplicate_item")["task_id"] == task
    assert await _launch_count(db_session, project_id) == 0
    assert await _reservation_count(db_session, project_id) == 0
    assert await _requested_events(client, auth_headers, project_id) == []


async def test_not_launchable_refused_with_exclusion_reasons(
    client: AsyncClient,
    auth_headers: Headers,
    db_session: AsyncSession,
) -> None:
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id, DEPENDENT)
    first = await _task(client, auth_headers, project_id)
    blocked = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", first)
    await _link(client, auth_headers, roadmap["id"], "S2", blocked)
    plan = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")

    response = await _admit(
        client,
        auth_headers,
        roadmap["id"],
        _batch(plan["plan_digest"], [(blocked, str(uuid.uuid4()))]),
    )
    assert response.status_code == 409, response.text
    refusal = _reason(response.json()["detail"], "not_launchable")
    assert refusal["task_id"] == blocked
    assert "dependency_pending" in refusal["exclusion_reasons"]
    assert await _launch_count(db_session, project_id) == 0
    assert await _reservation_count(db_session, project_id) == 0


async def test_machine_not_eligible_refused(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    other_model, _ = other_machine
    other_machine_id = str(other_model.id)
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    task = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", task)
    await _heartbeat(client, auth_headers, model.id, project_id)
    plan = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")

    response = await _admit(
        client,
        auth_headers,
        roadmap["id"],
        _batch(plan["plan_digest"], [(task, other_machine_id)]),
    )
    assert response.status_code == 409, response.text
    refusal = _reason(response.json()["detail"], "machine_not_eligible")
    assert refusal["task_id"] == task
    assert refusal["machine_id"] == other_machine_id
    assert await _launch_count(db_session, project_id) == 0
    assert await _reservation_count(db_session, project_id) == 0


async def test_replay_same_key_returns_the_same_result(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    first = await _task(client, auth_headers, project_id)
    second = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", first)
    await _link(client, auth_headers, roadmap["id"], "S2", second)
    await _heartbeat(client, auth_headers, model.id, project_id)
    plan = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")
    body = _batch(plan["plan_digest"], [(first, str(model.id)), (second, str(model.id))])
    key = f"adm-{uuid.uuid4()}"

    original = await _admit(client, auth_headers, roadmap["id"], body, key=key)
    replay = await _admit(client, auth_headers, roadmap["id"], body, key=key)
    assert original.status_code == 201, original.text
    assert replay.status_code == 201, replay.text
    assert replay.json() == original.json()
    assert await _launch_count(db_session, project_id) == 2
    assert len(await _requested_events(client, auth_headers, project_id)) == 2


async def _put_policy(client: AsyncClient, headers: Headers, project_id: str, **body: Any) -> Any:
    response = await client.put(
        f"/api/v1/projects/{project_id}/budget-policy", json=body, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_budget_refused_when_slots_exhausted(
    client: AsyncClient,
    auth_headers: Headers,
    admin_auth_headers: Headers,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    model, _ = machine
    project_id = await _project(client, auth_headers)
    roadmap = await _active_roadmap(client, auth_headers, project_id)
    first = await _task(client, auth_headers, project_id)
    second = await _task(client, auth_headers, project_id)
    await _link(client, auth_headers, roadmap["id"], "S1", first)
    await _link(client, auth_headers, roadmap["id"], "S2", second)
    await _heartbeat(client, auth_headers, model.id, project_id)

    policy = await _put_policy(
        client, auth_headers, project_id, mode="enforce", max_active_launches=1
    )
    approved = await client.post(
        f"/api/v1/projects/{project_id}/budget-policy/approve",
        json={"expected_version": policy["version"]},
        headers=admin_auth_headers,
    )
    assert approved.status_code == 200, approved.text

    plan = await _dry_run(client, auth_headers, roadmap["id"], "?harness_id=claude-code")
    response = await _admit(
        client,
        auth_headers,
        roadmap["id"],
        _batch(plan["plan_digest"], [(first, str(model.id)), (second, str(model.id))]),
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "admission_refused"
    refusal = _reason(detail, "budget_refused")
    assert refusal["budget"]["error_code"] == "budget_refused"
    assert refusal["budget"]["reason"] == "budget_slots_exhausted"
    assert await _launch_count(db_session, project_id) == 0
    assert await _reservation_count(db_session, project_id) == 0
