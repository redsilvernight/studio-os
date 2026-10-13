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
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.user import UserModel
from studio_api.services import budgets as budgets_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services import task_launches as launches_service

from tests.api.test_claims_concurrency import _warm_pool, real_client, real_engine
from tests.api.test_task_launches import _caps, _heartbeat

__all__ = ["real_client", "real_engine"]


@dataclass
class World:
    headers: dict[str, str]
    admin: dict[str, str]
    project_id: str
    task_id: str
    machine_id: str


@pytest_asyncio.fixture
async def world(real_engine: AsyncEngine, real_client: AsyncClient) -> AsyncIterator[World]:
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup:
        user = await provisioning_service.create_user(
            setup, "Budget Concurrency User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(
            setup, user.id, "budget-concurrency-machine"
        )
        admin = await provisioning_service.create_user(
            setup, "Budget Concurrency Admin", f"{uuid.uuid4()}@example.test", "admin"
        )
        admin_machine, admin_token = await provisioning_service.create_machine(
            setup, admin.id, "budget-concurrency-admin"
        )
    headers = {"Authorization": f"Bearer {token}"}
    project = await real_client.post(
        "/api/v1/projects",
        json={"slug": f"bud-{uuid.uuid4().hex[:8]}", "name": "Budget"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    task = await real_client.post(
        "/api/v1/tasks", json={"project_id": project_id, "title": "t"}, headers=headers
    )
    assert task.status_code == 201, task.text
    await _heartbeat(real_client, headers, str(machine.id), _caps(project_id))
    try:
        yield World(
            headers,
            {"Authorization": f"Bearer {admin_token}"},
            project_id,
            task.json()["id"],
            str(machine.id),
        )
    finally:
        pid = uuid.UUID(project_id)
        machines = (machine.id, admin_machine.id)
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(BudgetReservationModel).where(BudgetReservationModel.project_id == pid)
            )
            await cleanup.execute(
                delete(BudgetPolicyModel).where(BudgetPolicyModel.project_id == pid)
            )
            await cleanup.execute(delete(TaskLaunchModel).where(TaskLaunchModel.project_id == pid))
            await cleanup.execute(
                delete(EventModel).where(
                    or_(EventModel.project_id == pid, EventModel.machine_id.in_(machines))
                )
            )
            await cleanup.execute(
                delete(IdempotencyKeyModel).where(
                    IdempotencyKeyModel.endpoint.like(f"%/projects/{project_id}/%")
                )
            )
            await cleanup.execute(delete(TaskModel).where(TaskModel.project_id == pid))
            await cleanup.execute(delete(ProjectModel).where(ProjectModel.id == pid))
            await cleanup.execute(delete(MachineModel).where(MachineModel.id.in_(machines)))
            await cleanup.execute(delete(UserModel).where(UserModel.id.in_((user.id, admin.id))))
            await cleanup.commit()


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
        headers=world.admin,
    )
    assert approved.status_code == 200, approved.text


async def _race(
    client: AsyncClient, engine: AsyncEngine, world: World, count: int, *, same_key: bool = False
) -> list[Any]:
    await _warm_pool(async_sessionmaker(engine, expire_on_commit=False), count)
    shared = f"budget-{uuid.uuid4()}"
    return await asyncio.gather(
        *(
            client.post(
                f"/api/v1/projects/{world.project_id}/task-launches",
                headers={
                    **world.headers,
                    "Idempotency-Key": shared if same_key else str(uuid.uuid4()),
                },
                json={
                    "task_id": world.task_id,
                    "machine_id": world.machine_id,
                    "harness_id": "claude-code",
                },
            )
            for _ in range(count)
        )
    )


async def _counts(engine: AsyncEngine, project_id: str) -> tuple[int, int, int]:
    pid = uuid.UUID(project_id)
    async with async_sessionmaker(engine, expire_on_commit=False)() as check:
        launches = await check.scalar(
            select(func.count())
            .select_from(TaskLaunchModel)
            .where(TaskLaunchModel.project_id == pid)
        )
        reservations = await check.scalar(
            select(func.count())
            .select_from(BudgetReservationModel)
            .where(BudgetReservationModel.project_id == pid)
        )
        distinct = await check.scalar(
            select(func.count(func.distinct(BudgetReservationModel.task_launch_id))).where(
                BudgetReservationModel.project_id == pid
            )
        )
    return int(launches or 0), int(reservations or 0), int(distinct or 0)


@pytest.mark.parametrize(
    ("policy", "reason"),
    [
        ({"max_active_launches": 2}, "budget_slots_exhausted"),
        ({"cost_limit": "1", "reservation_cost": "0.5"}, "budget_cost_exhausted"),
    ],
)
async def test_simultaneous_admissions_never_exceed_the_admitted_budget(
    real_engine: AsyncEngine,
    real_client: AsyncClient,
    world: World,
    policy: dict[str, Any],
    reason: str,
) -> None:
    await _enforce(real_client, world, **policy)
    responses = await _race(real_client, real_engine, world, 8)
    codes = Counter(r.status_code for r in responses)
    assert codes == {201: 2, 409: 6}, [r.text for r in responses]
    assert {r.json()["detail"]["reason"] for r in responses if r.status_code == 409} == {reason}
    assert await _counts(real_engine, world.project_id) == (2, 2, 2)


async def test_simultaneous_replays_of_one_admission_reserve_once(
    real_engine: AsyncEngine, real_client: AsyncClient, world: World
) -> None:
    await _enforce(real_client, world, max_active_launches=5)
    responses = await _race(real_client, real_engine, world, 6, same_key=True)
    created = {r.json()["id"] for r in responses if r.status_code == 201}
    assert len(created) == 1, [r.text for r in responses]
    assert all(r.status_code in {201, 409} for r in responses)
    assert await _counts(real_engine, world.project_id) == (1, 1, 1)


async def test_a_crash_before_commit_leaves_neither_launch_nor_reservation(
    real_engine: AsyncEngine,
    real_client: AsyncClient,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enforce(real_client, world, max_active_launches=1)

    async def _crash(*_: Any, **__: Any) -> None:
        raise RuntimeError("crash before commit")

    monkeypatch.setattr(launches_service, "_commit_with_event", _crash)
    with pytest.raises(RuntimeError):
        await _race(real_client, real_engine, world, 1)
    monkeypatch.undo()
    assert await _counts(real_engine, world.project_id) == (0, 0, 0)
    responses = await _race(real_client, real_engine, world, 3)
    assert Counter(r.status_code for r in responses) == {201: 1, 409: 2}
    assert await _counts(real_engine, world.project_id) == (1, 1, 1)


async def test_reconciliation_after_crash_frees_the_slot_once(
    real_engine: AsyncEngine, real_client: AsyncClient, world: World
) -> None:
    await _enforce(real_client, world, max_active_launches=1, settle_after_seconds=0)
    first = await _race(real_client, real_engine, world, 1)
    assert first[0].status_code == 201
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as crash:
        launch = await crash.get(TaskLaunchModel, uuid.UUID(first[0].json()["id"]))
        assert launch is not None
        launch.status = "running"
        launch.expires_at = launch.created_at
        await crash.commit()

    async def _reconcile() -> int:
        async with session_factory() as session:
            policy = (
                await session.execute(
                    select(BudgetPolicyModel)
                    .where(BudgetPolicyModel.project_id == uuid.UUID(world.project_id))
                    .with_for_update()
                )
            ).scalar_one()
            settled = await budgets_service.reconcile(
                session, policy, launch.created_at.replace(year=launch.created_at.year + 1)
            )
            await session.commit()
            return settled

    await _warm_pool(session_factory, 4)
    assert sorted(await asyncio.gather(*(_reconcile() for _ in range(4)))) == [0, 0, 0, 1]
    responses = await _race(real_client, real_engine, world, 3)
    assert Counter(r.status_code for r in responses) == {201: 1, 409: 2}
