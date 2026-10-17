"""P05 pilot gate: the two-machine / two-task admission scenario (Mission
Control P05, additive).

Reuses the real-Postgres savepoint fixtures and the HTTP helpers of
`tests/api/test_admission_batch.py` / `tests/api/test_admission_dry_run.py`.
An admin caller sees every eligible machine, so M1 and M2 (two distinct
machines, each heartbeated for the project) both appear in a Task's
`machine_ids`.

Covers, end to end:
1. bounded parallelism — two independent Tasks admitted in one batch on M1/M2,
   never more active launches than the enforced slots, a third item refused by
   the budget;
2. the dependency gate — a dependent Task is excluded (`dependency_pending`) in
   the dry-run and refused (`not_launchable`) in `admit` until its upstream Task
   has a *completed* handoff (making the upstream step `done`), then admitted
   exactly once;
3. the replay of the same `Idempotency-Key` after unblocking: same launches,
   no duplicate.
"""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.budget import BudgetReservationModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel

from tests.api.test_admission_batch import (
    _active_roadmap,
    _admit,
    _batch,
    _dry_run,
    _heartbeat,
    _link,
    _project,
    _put_policy,
    _reason,
    _task,
)
from tests.api.test_admission_dry_run import _exclusion

Headers = dict[str, str]

_ACTIVE_STATUSES = ("requested", "accepted", "preparing", "running")

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
                {"key": "S3", "title": "Step three"},
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


async def _launch_count(session: AsyncSession, project_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(TaskLaunchModel)
            .where(TaskLaunchModel.project_id == uuid.UUID(project_id))
        )
        or 0
    )


async def _active_launch_count(session: AsyncSession, project_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(TaskLaunchModel)
            .where(
                TaskLaunchModel.project_id == uuid.UUID(project_id),
                TaskLaunchModel.status.in_(_ACTIVE_STATUSES),
            )
        )
        or 0
    )


async def _active_for_task(session: AsyncSession, task_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(TaskLaunchModel)
            .where(
                TaskLaunchModel.task_id == uuid.UUID(task_id),
                TaskLaunchModel.status.in_(_ACTIVE_STATUSES),
            )
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


async def _enforce(client: AsyncClient, headers: Headers, project_id: str, **limits: Any) -> None:
    policy = await _put_policy(client, headers, project_id, mode="enforce", **limits)
    approved = await client.post(
        f"/api/v1/projects/{project_id}/budget-policy/approve",
        json={"expected_version": policy["version"]},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text


async def _handoff(
    client: AsyncClient,
    headers: Headers,
    project_id: str,
    machine_id: uuid.UUID,
    task_id: str,
    status: str,
) -> dict[str, Any]:
    """Open a work session on the Task and close it with `studio_handoff`,
    applying `status` to the Task. Reuses the composed handoff service."""
    created = await client.post(
        "/api/v1/sessions",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"task_id": task_id, "machine_id": str(machine_id)},
    )
    assert created.status_code == 201, created.text
    version = (await client.get(f"/api/v1/tasks/{task_id}", headers=headers)).json()["version"]
    handoff = await client.post(
        "/api/v1/handoff",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": project_id,
            "session_id": created.json()["id"],
            "expected_version": version,
            "task_status": {"status": status},
        },
    )
    assert handoff.status_code == 200, handoff.text
    assert handoff.json()["task_status"] == status
    return handoff.json()  # type: ignore[no-any-return]


async def _two_machines(
    client: AsyncClient,
    auth_headers: Headers,
    other_auth_headers: Headers,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    project_id: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Both M1 and M2 report a fresh heartbeat registered on the project, so
    the admin caller sees two eligible machines in every dry-run. The ids are
    captured as plain values: a refused admission rolls the shared savepoint
    back, which expires every ORM instance of the session."""
    model, _ = machine
    other_model, _ = other_machine
    await _heartbeat(client, auth_headers, model.id, project_id)
    await _heartbeat(client, other_auth_headers, other_model.id, project_id)
    return model.id, other_model.id


async def test_bounded_parallelism_across_two_machines_refuses_the_third_item(
    client: AsyncClient,
    admin_auth_headers: Headers,
    auth_headers: Headers,
    other_auth_headers: Headers,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id = await _project(client, admin_auth_headers)
    roadmap = await _active_roadmap(client, admin_auth_headers, project_id, INDEPENDENT)
    first = await _task(client, admin_auth_headers, project_id)
    second = await _task(client, admin_auth_headers, project_id)
    third = await _task(client, admin_auth_headers, project_id)
    await _link(client, admin_auth_headers, roadmap["id"], "S1", first)
    await _link(client, admin_auth_headers, roadmap["id"], "S2", second)
    await _link(client, admin_auth_headers, roadmap["id"], "S3", third)
    model, other_model = await _two_machines(
        client, auth_headers, other_auth_headers, machine, other_machine, project_id
    )
    await _enforce(client, admin_auth_headers, project_id, max_active_launches=2)

    plan = await _dry_run(client, admin_auth_headers, roadmap["id"], "?harness_id=claude-code")
    assert {c["task_id"] for c in plan["launchable"]} == {first, second, third}
    assert {machine_id for c in plan["launchable"] for machine_id in c["machine_ids"]} == {
        str(model),
        str(other_model),
    }

    admitted = await _admit(
        client,
        admin_auth_headers,
        roadmap["id"],
        _batch(plan["plan_digest"], [(first, str(model)), (second, str(other_model))]),
        key=f"pilot-{uuid.uuid4()}",
    )
    assert admitted.status_code == 201, admitted.text
    launches = {launch["task_id"]: launch["machine_id"] for launch in admitted.json()["launches"]}
    assert launches == {first: str(model), second: str(other_model)}
    assert all(launch["status"] == "requested" for launch in admitted.json()["launches"])
    active = await _active_launch_count(db_session, project_id)
    assert active == 2
    assert active <= 2

    after = await _dry_run(client, admin_auth_headers, roadmap["id"], "?harness_id=claude-code")
    assert [c["task_id"] for c in after["launchable"]] == [third]

    refused = await _admit(
        client,
        admin_auth_headers,
        roadmap["id"],
        _batch(after["plan_digest"], [(third, str(model))]),
        key=f"pilot-{uuid.uuid4()}",
    )
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["error_code"] == "admission_refused"
    budget_refusal = _reason(detail, "budget_refused")
    assert budget_refusal["task_id"] == third
    assert budget_refusal["budget"]["reason"] == "budget_slots_exhausted"
    assert await _active_launch_count(db_session, project_id) == 2
    assert await _launch_count(db_session, project_id) == 2
    assert await _reservation_count(db_session, project_id) == 2


async def test_dependent_task_is_gated_until_its_upstream_handoff_completes(
    client: AsyncClient,
    admin_auth_headers: Headers,
    auth_headers: Headers,
    other_auth_headers: Headers,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id = await _project(client, admin_auth_headers)
    roadmap = await _active_roadmap(client, admin_auth_headers, project_id, DEPENDENT)
    upstream = await _task(client, admin_auth_headers, project_id)
    dependent = await _task(client, admin_auth_headers, project_id)
    await _link(client, admin_auth_headers, roadmap["id"], "S1", upstream)
    await _link(client, admin_auth_headers, roadmap["id"], "S2", dependent)
    model, other_model = await _two_machines(
        client, auth_headers, other_auth_headers, machine, other_machine, project_id
    )

    plan = await _dry_run(client, admin_auth_headers, roadmap["id"], "?harness_id=claude-code")
    assert [c["task_id"] for c in plan["launchable"]] == [upstream]
    exclusion = _exclusion(plan, dependent)
    assert "dependency_pending" in exclusion["reasons"]
    assert exclusion["waiting_on"] == ["S1"]

    refused = await _admit(
        client,
        admin_auth_headers,
        roadmap["id"],
        _batch(plan["plan_digest"], [(dependent, str(model))]),
        key=f"pilot-{uuid.uuid4()}",
    )
    assert refused.status_code == 409, refused.text
    refusal = _reason(refused.json()["detail"], "not_launchable")
    assert refusal["task_id"] == dependent
    assert "dependency_pending" in refusal["exclusion_reasons"]
    assert await _launch_count(db_session, project_id) == 0

    # A handoff that does not complete the upstream Task leaves the step
    # not `done`, so the dependent Task stays gated.
    await _handoff(client, auth_headers, project_id, model, upstream, "in_progress")
    still_blocked = await _dry_run(
        client, admin_auth_headers, roadmap["id"], "?harness_id=claude-code"
    )
    assert "dependency_pending" in _exclusion(still_blocked, dependent)["reasons"]

    # A *completed* handoff makes S1 `done`; the dependent Task becomes
    # launchable and is admitted exactly once.
    await _handoff(client, auth_headers, project_id, model, upstream, "completed")
    unblocked = await _dry_run(client, admin_auth_headers, roadmap["id"], "?harness_id=claude-code")
    assert [c["task_id"] for c in unblocked["launchable"]] == [dependent]
    assert dependent not in {e["task_id"] for e in unblocked["excluded"]}

    admitted = await _admit(
        client,
        admin_auth_headers,
        roadmap["id"],
        _batch(unblocked["plan_digest"], [(dependent, str(other_model))]),
        key=f"pilot-{uuid.uuid4()}",
    )
    assert admitted.status_code == 201, admitted.text
    assert [launch["task_id"] for launch in admitted.json()["launches"]] == [dependent]
    assert await _active_for_task(db_session, dependent) == 1
    assert await _launch_count(db_session, project_id) == 1

    # Exactly once: admitting it again creates nothing (an active launch now
    # excludes it from the plan).
    twice = await _dry_run(client, admin_auth_headers, roadmap["id"], "?harness_id=claude-code")
    assert "launch_active" in _exclusion(twice, dependent)["reasons"]
    retry = await _admit(
        client,
        admin_auth_headers,
        roadmap["id"],
        _batch(twice["plan_digest"], [(dependent, str(model))]),
        key=f"pilot-{uuid.uuid4()}",
    )
    assert retry.status_code == 409, retry.text
    assert await _launch_count(db_session, project_id) == 1
    assert await _active_for_task(db_session, dependent) == 1


async def test_replay_of_the_same_key_after_unblocking_has_no_duplicate(
    client: AsyncClient,
    admin_auth_headers: Headers,
    auth_headers: Headers,
    other_auth_headers: Headers,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id = await _project(client, admin_auth_headers)
    roadmap = await _active_roadmap(client, admin_auth_headers, project_id, DEPENDENT)
    upstream = await _task(client, admin_auth_headers, project_id)
    dependent = await _task(client, admin_auth_headers, project_id)
    await _link(client, admin_auth_headers, roadmap["id"], "S1", upstream)
    await _link(client, admin_auth_headers, roadmap["id"], "S2", dependent)
    model, _ = await _two_machines(
        client, auth_headers, other_auth_headers, machine, other_machine, project_id
    )
    key = f"pilot-{uuid.uuid4()}"

    blocked = await _dry_run(client, admin_auth_headers, roadmap["id"], "?harness_id=claude-code")
    refused = await _admit(
        client,
        admin_auth_headers,
        roadmap["id"],
        _batch(blocked["plan_digest"], [(dependent, str(model))]),
        key=key,
    )
    assert refused.status_code == 409, refused.text
    assert await _launch_count(db_session, project_id) == 0

    await _handoff(client, auth_headers, project_id, model, upstream, "completed")
    unblocked = await _dry_run(client, admin_auth_headers, roadmap["id"], "?harness_id=claude-code")

    original = await _admit(
        client,
        admin_auth_headers,
        roadmap["id"],
        _batch(unblocked["plan_digest"], [(dependent, str(model))]),
        key=key,
    )
    replay = await _admit(
        client,
        admin_auth_headers,
        roadmap["id"],
        _batch(unblocked["plan_digest"], [(dependent, str(model))]),
        key=key,
    )
    assert original.status_code == 201, original.text
    assert replay.status_code == 201, replay.text
    assert replay.json() == original.json()
    assert {launch["id"] for launch in replay.json()["launches"]} == {
        launch["id"] for launch in original.json()["launches"]
    }
    assert await _launch_count(db_session, project_id) == 1
    assert await _active_for_task(db_session, dependent) == 1
