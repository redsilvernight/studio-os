"""Genuine-Postgres concurrency acceptance of the roadmap admission batch
(Mission Control P05, additive).

Modeled on `tests/api/test_budgets_concurrency.py` and
`tests/api/test_idempotency_concurrency.py`: each concurrent request runs in
its own independently-committing connection (`real_engine`/`real_client`),
never the shared-savepoint `db_session`, so the races really happen at
Postgres. The fixtures (active roadmap, steps, linked tasks, an online machine
advertising `accepts_launches`) reuse `tests/api/test_admission_dry_run.py`
helpers.

The `POST /api/v1/roadmaps/{roadmap_id}/admission` endpoint is implemented in a
parallel branch: these tests are written against
`studio_contracts.admission.AdmissionBatchRequest/Result/Refused` and the
frozen contract in `docs/.../TECH/02_API_CONTRACT.md` ("Roadmap admission
dry-run"). They are expected to pass once that endpoint lands.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from studio_api.db.models.budget import BudgetPolicyModel, BudgetReservationModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.idempotency import IdempotencyKeyModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.roadmap import RoadmapModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.user import UserModel
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services import task_launches as launches_service

from tests.api.test_admission_dry_run import _active_roadmap, _link, _task
from tests.api.test_claims_concurrency import _warm_pool, real_client, real_engine
from tests.api.test_task_launches import _caps, _heartbeat

__all__ = ["real_client", "real_engine"]

_HARNESS = "claude-code"
_ACTIVE_LAUNCH_STATUSES = frozenset({"requested", "accepted", "preparing", "running"})

DOCUMENT: dict[str, Any] = {
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
                {"key": "S4", "title": "Step four"},
            ],
        }
    ],
}


@dataclass
class World:
    headers: dict[str, str]
    other_headers: dict[str, str]
    admin_headers: dict[str, str]
    project_id: str
    machine_id: str
    other_machine_id: str


@pytest_asyncio.fixture
async def world(real_engine: AsyncEngine, real_client: AsyncClient) -> AsyncIterator[World]:
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup:
        user = await provisioning_service.create_user(
            setup, "Admission User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(
            setup, user.id, "admission-machine"
        )
        other = await provisioning_service.create_user(
            setup, "Admission Other", f"{uuid.uuid4()}@example.test", "developer"
        )
        other_machine, other_token = await provisioning_service.create_machine(
            setup, other.id, "admission-other-machine"
        )
        admin = await provisioning_service.create_user(
            setup, "Admission Admin", f"{uuid.uuid4()}@example.test", "admin"
        )
        admin_machine, admin_token = await provisioning_service.create_machine(
            setup, admin.id, "admission-admin-machine"
        )

    headers = {"Authorization": f"Bearer {token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    project = await real_client.post(
        "/api/v1/projects",
        json={"slug": f"adm-{uuid.uuid4().hex[:8]}", "name": "Admission"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    async with session_factory() as grant:
        await projects_service.grant_member(
            grant, uuid.UUID(project_id), other.id, granted_by_user_id=user.id
        )
    await _heartbeat(real_client, headers, str(machine.id), _caps(project_id))
    await _heartbeat(real_client, other_headers, str(other_machine.id), _caps(project_id))
    try:
        yield World(
            headers,
            other_headers,
            admin_headers,
            project_id,
            str(machine.id),
            str(other_machine.id),
        )
    finally:
        pid = uuid.UUID(project_id)
        machines = (machine.id, other_machine.id, admin_machine.id)
        users = (user.id, other.id, admin.id)
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(BudgetReservationModel).where(BudgetReservationModel.project_id == pid)
            )
            await cleanup.execute(
                delete(BudgetPolicyModel).where(BudgetPolicyModel.project_id == pid)
            )
            await cleanup.execute(delete(TaskLaunchModel).where(TaskLaunchModel.project_id == pid))
            await cleanup.execute(delete(RoadmapModel).where(RoadmapModel.project_id == pid))
            await cleanup.execute(
                delete(EventModel).where(
                    or_(EventModel.project_id == pid, EventModel.machine_id.in_(machines))
                )
            )
            await cleanup.execute(
                delete(IdempotencyKeyModel).where(
                    or_(
                        IdempotencyKeyModel.endpoint.like("%/admission"),
                        IdempotencyKeyModel.endpoint.like(f"%/projects/{project_id}/%"),
                    )
                )
            )
            await cleanup.execute(delete(TaskModel).where(TaskModel.project_id == pid))
            await cleanup.execute(delete(ProjectModel).where(ProjectModel.id == pid))
            await cleanup.execute(delete(MachineModel).where(MachineModel.id.in_(machines)))
            await cleanup.execute(delete(UserModel).where(UserModel.id.in_(users)))
            await cleanup.commit()


async def _plan(client: AsyncClient, headers: dict[str, str], roadmap_id: str) -> dict[str, Any]:
    response = await client.get(
        f"/api/v1/roadmaps/{roadmap_id}/admission/dry-run?harness_id={_HARNESS}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _machine_for(plan: dict[str, Any], task_id: str) -> str:
    candidate = next(item for item in plan["launchable"] if item["task_id"] == task_id)
    return str(candidate["machine_ids"][0])


async def _admit(
    client: AsyncClient,
    roadmap_id: str,
    headers: dict[str, str],
    *,
    digest: str,
    machine_id: str,
    task_ids: list[str],
    key: str,
) -> Any:
    body = {
        "plan_digest": digest,
        "harness_id": _HARNESS,
        "items": [{"task_id": task_id, "machine_id": machine_id} for task_id in task_ids],
    }
    return await client.post(
        f"/api/v1/roadmaps/{roadmap_id}/admission",
        json=body,
        headers={**headers, "Idempotency-Key": key},
    )


async def _launch_unit(
    client: AsyncClient, headers: dict[str, str], project_id: str, task_id: str, machine_id: str
) -> Any:
    return await client.post(
        f"/api/v1/projects/{project_id}/task-launches",
        json={"task_id": task_id, "machine_id": machine_id, "harness_id": _HARNESS},
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )


async def _enforce(client: AsyncClient, world: World, **body: Any) -> None:
    policy = await client.put(
        f"/api/v1/projects/{world.project_id}/budget-policy",
        json={"mode": "enforce", **body},
        headers=world.headers,
    )
    assert policy.status_code == 200, policy.text
    approved = await client.post(
        f"/api/v1/projects/{world.project_id}/budget-policy/approve",
        json={"expected_version": policy.json()["version"]},
        headers=world.admin_headers,
    )
    assert approved.status_code == 200, approved.text


async def _launch_counts(engine: AsyncEngine, project_id: str) -> tuple[int, int]:
    pid = uuid.UUID(project_id)
    async with async_sessionmaker(engine, expire_on_commit=False)() as check:
        launches = await check.scalar(
            select(func.count())
            .select_from(TaskLaunchModel)
            .where(TaskLaunchModel.project_id == pid)
        )
        held = await check.scalar(
            select(func.count())
            .select_from(BudgetReservationModel)
            .where(
                BudgetReservationModel.project_id == pid,
                BudgetReservationModel.status == "held",
            )
        )
    return int(launches or 0), int(held or 0)


async def _active_for_task(engine: AsyncEngine, task_id: str) -> int:
    async with async_sessionmaker(engine, expire_on_commit=False)() as check:
        count = await check.scalar(
            select(func.count())
            .select_from(TaskLaunchModel)
            .where(
                TaskLaunchModel.task_id == uuid.UUID(task_id),
                TaskLaunchModel.status.in_(_ACTIVE_LAUNCH_STATUSES),
            )
        )
    return int(count or 0)


def _error_code(response: Any) -> Any:
    return response.json()["detail"]["error_code"]


async def test_two_batches_same_plan_accept_exactly_one(
    real_engine: AsyncEngine, real_client: AsyncClient, world: World
) -> None:
    roadmap = await _active_roadmap(real_client, world.headers, world.project_id, DOCUMENT)
    first = await _task(real_client, world.headers, world.project_id)
    second = await _task(real_client, world.headers, world.project_id)
    await _link(real_client, world.headers, roadmap["id"], "S1", first)
    await _link(real_client, world.headers, roadmap["id"], "S2", second)

    plan = await _plan(real_client, world.headers, roadmap["id"])
    digest = plan["plan_digest"]
    machine_id = _machine_for(plan, first)

    await _warm_pool(async_sessionmaker(real_engine, expire_on_commit=False), 2)
    responses = await asyncio.gather(
        _admit(
            real_client,
            roadmap["id"],
            world.headers,
            digest=digest,
            machine_id=machine_id,
            task_ids=[first, second],
            key=str(uuid.uuid4()),
        ),
        _admit(
            real_client,
            roadmap["id"],
            world.headers,
            digest=digest,
            machine_id=machine_id,
            task_ids=[first, second],
            key=str(uuid.uuid4()),
        ),
    )

    assert Counter(r.status_code for r in responses) == {201: 1, 409: 1}, [
        r.text for r in responses
    ]
    loser = next(r for r in responses if r.status_code == 409)
    assert _error_code(loser) == "admission_plan_changed"
    assert await _active_for_task(real_engine, first) == 1
    assert await _active_for_task(real_engine, second) == 1
    assert await _launch_counts(real_engine, world.project_id) == (2, 0)


async def test_two_users_racing_the_same_task_accept_exactly_one(
    real_engine: AsyncEngine, real_client: AsyncClient, world: World
) -> None:
    roadmap = await _active_roadmap(real_client, world.headers, world.project_id, DOCUMENT)
    task_id = await _task(real_client, world.headers, world.project_id)
    await _link(real_client, world.headers, roadmap["id"], "S1", task_id)

    plan = await _plan(real_client, world.headers, roadmap["id"])
    other_plan = await _plan(real_client, world.other_headers, roadmap["id"])

    await _warm_pool(async_sessionmaker(real_engine, expire_on_commit=False), 2)
    responses = await asyncio.gather(
        _admit(
            real_client,
            roadmap["id"],
            world.headers,
            digest=plan["plan_digest"],
            machine_id=_machine_for(plan, task_id),
            task_ids=[task_id],
            key=str(uuid.uuid4()),
        ),
        _admit(
            real_client,
            roadmap["id"],
            world.other_headers,
            digest=other_plan["plan_digest"],
            machine_id=_machine_for(other_plan, task_id),
            task_ids=[task_id],
            key=str(uuid.uuid4()),
        ),
    )

    assert Counter(r.status_code for r in responses) == {201: 1, 409: 1}, [
        r.text for r in responses
    ]
    loser = next(r for r in responses if r.status_code == 409)
    assert _error_code(loser) == "admission_plan_changed"
    assert await _active_for_task(real_engine, task_id) == 1
    assert await _launch_counts(real_engine, world.project_id) == (1, 0)


async def test_concurrent_replays_of_one_key_share_the_same_launches(
    real_engine: AsyncEngine, real_client: AsyncClient, world: World
) -> None:
    roadmap = await _active_roadmap(real_client, world.headers, world.project_id, DOCUMENT)
    task_id = await _task(real_client, world.headers, world.project_id)
    await _link(real_client, world.headers, roadmap["id"], "S1", task_id)

    plan = await _plan(real_client, world.headers, roadmap["id"])
    shared_key = str(uuid.uuid4())

    await _warm_pool(async_sessionmaker(real_engine, expire_on_commit=False), 2)
    responses = await asyncio.gather(
        *(
            _admit(
                real_client,
                roadmap["id"],
                world.headers,
                digest=plan["plan_digest"],
                machine_id=_machine_for(plan, task_id),
                task_ids=[task_id],
                key=shared_key,
            )
            for _ in range(4)
        )
    )

    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    created = {launch["id"] for r in responses for launch in r.json()["launches"]}
    assert len(created) == 1, [r.text for r in responses]
    assert await _active_for_task(real_engine, task_id) == 1
    assert await _launch_counts(real_engine, world.project_id) == (1, 0)


async def test_two_batches_cannot_exceed_the_admitted_slots(
    real_engine: AsyncEngine, real_client: AsyncClient, world: World
) -> None:
    await _enforce(real_client, world, max_active_launches=2)
    roadmap = await _active_roadmap(real_client, world.headers, world.project_id, DOCUMENT)
    tasks = [await _task(real_client, world.headers, world.project_id) for _ in range(4)]
    for step_key, task_id in zip(("S1", "S2", "S3", "S4"), tasks, strict=True):
        await _link(real_client, world.headers, roadmap["id"], step_key, task_id)
    tasks_a, tasks_b = tasks[:2], tasks[2:]
    plan = await _plan(real_client, world.headers, roadmap["id"])

    await _warm_pool(async_sessionmaker(real_engine, expire_on_commit=False), 2)
    responses = await asyncio.gather(
        _admit(
            real_client,
            roadmap["id"],
            world.headers,
            digest=plan["plan_digest"],
            machine_id=_machine_for(plan, tasks_a[0]),
            task_ids=tasks_a,
            key=str(uuid.uuid4()),
        ),
        _admit(
            real_client,
            roadmap["id"],
            world.headers,
            digest=plan["plan_digest"],
            machine_id=_machine_for(plan, tasks_b[0]),
            task_ids=tasks_b,
            key=str(uuid.uuid4()),
        ),
    )

    assert Counter(r.status_code for r in responses) == {201: 1, 409: 1}, [
        r.text for r in responses
    ]
    loser = next(r for r in responses if r.status_code == 409)
    assert _error_code(loser) in {"admission_plan_changed", "admission_refused"}
    details = loser.json()["detail"]
    if details["error_code"] == "admission_refused":
        assert "budget_refused" in {refusal["reason"] for refusal in details["refusals"]}
    assert await _launch_counts(real_engine, world.project_id) == (2, 2)


async def test_a_crash_before_commit_leaves_nothing_then_a_replay_succeeds(
    real_engine: AsyncEngine,
    real_client: AsyncClient,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enforce(real_client, world, max_active_launches=2)
    roadmap = await _active_roadmap(real_client, world.headers, world.project_id, DOCUMENT)
    first = await _task(real_client, world.headers, world.project_id)
    second = await _task(real_client, world.headers, world.project_id)
    await _link(real_client, world.headers, roadmap["id"], "S1", first)
    await _link(real_client, world.headers, roadmap["id"], "S2", second)

    plan = await _plan(real_client, world.headers, roadmap["id"])
    machine_id = _machine_for(plan, first)
    key = str(uuid.uuid4())

    original_stage = launches_service.stage_launch
    staged = {"count": 0}

    async def _crash_after_first_stage(*args: Any, **kwargs: Any) -> Any:
        staged["count"] += 1
        if staged["count"] >= 2:
            raise RuntimeError("crash after staging the launches, before commit")
        return await original_stage(*args, **kwargs)

    monkeypatch.setattr(launches_service, "stage_launch", _crash_after_first_stage)
    crashed: Any = None
    try:
        crashed = await _admit(
            real_client,
            roadmap["id"],
            world.headers,
            digest=plan["plan_digest"],
            machine_id=machine_id,
            task_ids=[first, second],
            key=key,
        )
    except RuntimeError:
        crashed = None
    if crashed is not None:
        assert crashed.status_code >= 500, crashed.text
    monkeypatch.undo()

    assert await _launch_counts(real_engine, world.project_id) == (0, 0)

    replayed = await _admit(
        real_client,
        roadmap["id"],
        world.headers,
        digest=plan["plan_digest"],
        machine_id=machine_id,
        task_ids=[first, second],
        key=key,
    )
    assert replayed.status_code == 201, replayed.text
    assert len(replayed.json()["launches"]) == 2
    assert await _launch_counts(real_engine, world.project_id) == (2, 2)


async def test_unit_launch_committed_first_makes_the_batch_refuse(
    real_engine: AsyncEngine, real_client: AsyncClient, world: World
) -> None:
    roadmap = await _active_roadmap(real_client, world.headers, world.project_id, DOCUMENT)
    task_id = await _task(real_client, world.headers, world.project_id)
    await _link(real_client, world.headers, roadmap["id"], "S1", task_id)

    plan = await _plan(real_client, world.headers, roadmap["id"])
    machine_id = _machine_for(plan, task_id)

    unit = await _launch_unit(real_client, world.headers, world.project_id, task_id, machine_id)
    assert unit.status_code == 201, unit.text
    assert await _active_for_task(real_engine, task_id) == 1

    batch = await _admit(
        real_client,
        roadmap["id"],
        world.headers,
        digest=plan["plan_digest"],
        machine_id=machine_id,
        task_ids=[task_id],
        key=str(uuid.uuid4()),
    )
    assert batch.status_code == 409, batch.text
    assert _error_code(batch) == "admission_plan_changed"
    assert await _active_for_task(real_engine, task_id) == 1
    assert await _launch_counts(real_engine, world.project_id) == (1, 0)


async def test_batch_committed_first_lets_a_later_unit_launch_add_a_second(
    real_engine: AsyncEngine, real_client: AsyncClient, world: World
) -> None:
    """Documented DEC-0218 limit: the unit-launch route has no `launch_active`
    guard, so a unit launch fired after the batch may still create a second
    active launch on the same task. Asserted as an accepted outcome, never as
    the batch's guarantee."""
    roadmap = await _active_roadmap(real_client, world.headers, world.project_id, DOCUMENT)
    task_id = await _task(real_client, world.headers, world.project_id)
    await _link(real_client, world.headers, roadmap["id"], "S1", task_id)

    plan = await _plan(real_client, world.headers, roadmap["id"])
    machine_id = _machine_for(plan, task_id)

    batch = await _admit(
        real_client,
        roadmap["id"],
        world.headers,
        digest=plan["plan_digest"],
        machine_id=machine_id,
        task_ids=[task_id],
        key=str(uuid.uuid4()),
    )
    assert batch.status_code == 201, batch.text
    assert len(batch.json()["launches"]) == 1

    unit = await _launch_unit(real_client, world.headers, world.project_id, task_id, machine_id)
    assert unit.status_code in {201, 409}, unit.text
    active = await _active_for_task(real_engine, task_id)
    assert active == (2 if unit.status_code == 201 else 1)
    assert (await _launch_counts(real_engine, world.project_id))[0] == active


async def test_concurrent_batch_never_launches_an_already_active_task(
    real_engine: AsyncEngine, real_client: AsyncClient, world: World
) -> None:
    roadmap = await _active_roadmap(real_client, world.headers, world.project_id, DOCUMENT)
    task_id = await _task(real_client, world.headers, world.project_id)
    await _link(real_client, world.headers, roadmap["id"], "S1", task_id)

    plan = await _plan(real_client, world.headers, roadmap["id"])
    machine_id = _machine_for(plan, task_id)

    await _warm_pool(async_sessionmaker(real_engine, expire_on_commit=False), 2)
    batch_response, unit_response = await asyncio.gather(
        _admit(
            real_client,
            roadmap["id"],
            world.headers,
            digest=plan["plan_digest"],
            machine_id=machine_id,
            task_ids=[task_id],
            key=str(uuid.uuid4()),
        ),
        _launch_unit(real_client, world.headers, world.project_id, task_id, machine_id),
    )

    assert batch_response.status_code in {201, 409}, batch_response.text
    if batch_response.status_code == 201:
        assert len(batch_response.json()["launches"]) == 1
        assert unit_response.status_code in {201, 409}, unit_response.text
    else:
        # A refused batch means it recomputed the plan after the unit launch
        # committed: it must carry `admission_plan_changed` and create nothing.
        assert _error_code(batch_response) == "admission_plan_changed"
        assert unit_response.status_code == 201, unit_response.text
    launched = await _launch_counts(real_engine, world.project_id)
    assert launched[0] == await _active_for_task(real_engine, task_id)
    assert launched[0] <= 2
