from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.budget import BudgetReservationModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.usage import UsageLedgerEntryModel
from studio_api.services import budgets as budgets_service
from studio_contracts.budgets import BudgetRefusal, BudgetStatus

from tests.api.test_task_launches import _launch, _ready_target

World = tuple[str, str, str]


async def _world(
    client: AsyncClient, headers: dict[str, str], machine: tuple[MachineModel, str]
) -> World:
    return await _ready_target(client, headers, machine)


async def _put_policy(
    client: AsyncClient, headers: dict[str, str], project_id: str, **body: Any
) -> Any:
    response = await client.put(
        f"/api/v1/projects/{project_id}/budget-policy", json=body, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _approve(
    client: AsyncClient, headers: dict[str, str], project_id: str, version: int
) -> Any:
    return await client.post(
        f"/api/v1/projects/{project_id}/budget-policy/approve",
        json={"expected_version": version},
        headers=headers,
    )


async def _enforced(
    client: AsyncClient,
    headers: dict[str, str],
    admin: dict[str, str],
    project_id: str,
    **body: Any,
) -> Any:
    policy = await _put_policy(client, headers, project_id, mode="enforce", **body)
    approved = await _approve(client, admin, project_id, policy["version"])
    assert approved.status_code == 200, approved.text
    return approved.json()


async def _status(client: AsyncClient, headers: dict[str, str], project_id: str) -> BudgetStatus:
    response = await client.get(f"/api/v1/projects/{project_id}/budget", headers=headers)
    assert response.status_code == 200, response.text
    return BudgetStatus.model_validate(response.json())


async def _admit(client: AsyncClient, headers: dict[str, str], world: World, **kw: Any) -> Any:
    project_id, task_id, machine_id = world
    return await _launch(client, headers, project_id, task_id, machine_id, **kw)


def _meter(status: BudgetStatus, metric: str) -> Any:
    return next(m for m in status.meters if m.metric == metric)


async def _finish(
    db: AsyncSession, launch_id: str, *, ago: timedelta, status: str = "succeeded", **extra: Any
) -> None:
    await db.execute(
        update(TaskLaunchModel)
        .where(TaskLaunchModel.id == uuid.UUID(launch_id))
        .values(status=status, finished_at=datetime.now(UTC) - ago, **extra)
    )
    await db.flush()


async def _usage(
    db: AsyncSession, world: World, launch_id: str | None, **measures: Any
) -> UsageLedgerEntryModel:
    project_id, _, machine_id = world
    now = datetime.now(UTC)
    entry = UsageLedgerEntryModel(
        project_id=uuid.UUID(project_id),
        machine_id=uuid.UUID(machine_id),
        task_launch_id=uuid.UUID(launch_id) if launch_id else None,
        source_event_id=f"evt-{uuid.uuid4().hex}",
        collector="runtime",
        period_start=now,
        period_end=now,
        version=1,
        **measures,
    )
    db.add(entry)
    await db.flush()
    return entry


def _cost(value: str) -> dict[str, Any]:
    return {"cost": Decimal(value), "cost_coverage": "measured", "cost_currency": "USD"}


async def _launch_count(db: AsyncSession, project_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(TaskLaunchModel)
            .where(TaskLaunchModel.project_id == uuid.UUID(project_id))
        )
        or 0
    )


async def test_without_policy_everything_is_admitted_and_nothing_promised(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    response = await _admit(client, auth_headers, world)
    assert response.status_code == 201, response.text
    status = await _status(client, auth_headers, world[0])
    assert status.policy is None
    assert status.effective_mode == "alert_only"
    assert status.ceiling_guarantee == "none"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(BudgetReservationModel)
            .where(BudgetReservationModel.task_launch_id == uuid.UUID(response.json()["id"]))
        )
        == 0
    )


async def test_default_policy_is_alert_only_and_admits_past_its_limit(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    world = await _world(client, auth_headers, machine)
    policy = await _put_policy(
        client, auth_headers, world[0], cost_limit="1", reservation_cost="0.6"
    )
    assert policy["mode"] == "alert_only"
    assert policy["approval_status"] == "not_required"
    assert policy["ceiling_guarantee"] == "none"
    for _ in range(2):
        assert (await _admit(client, auth_headers, world)).status_code == 201
    status = await _status(client, auth_headers, world[0])
    cost = _meter(status, "cost")
    assert cost.held == Decimal("1.2")
    assert cost.consumed == 0
    alerts = {
        (a.code.value, a.metric.value if a.metric else None, a.threshold)
        for r in status.reservations
        for a in r.alerts
    }
    assert ("limit_exceeded", "cost", None) in alerts
    assert ("threshold_reached", "cost", 100) in alerts
    assert ("threshold_reached", "cost", 80) in alerts


async def test_enforce_needs_an_admin_approval_before_refusing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    policy = await _put_policy(
        client, auth_headers, world[0], mode="enforce", max_active_launches=1
    )
    assert policy["approval_status"] == "pending"
    assert policy["effective_mode"] == "alert_only"
    for _ in range(2):
        assert (await _admit(client, auth_headers, world)).status_code == 201
    status = await _status(client, auth_headers, world[0])
    codes = {a.code.value for r in status.reservations for a in r.alerts}
    assert {"enforce_pending_approval", "slots_exhausted"} <= codes

    own = await _approve(client, auth_headers, world[0], policy["version"])
    assert own.status_code == 403, own.text
    approved = await _approve(client, admin_auth_headers, world[0], policy["version"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_status"] == "approved"
    assert approved.json()["ceiling_guarantee"] == "admission_only"
    again = await _approve(client, admin_auth_headers, world[0], approved.json()["version"])
    assert again.status_code == 409
    assert again.json()["detail"]["error_code"] == "budget_approval_not_pending"

    before = await _launch_count(db_session, world[0])
    refused = await _admit(client, auth_headers, world)
    assert refused.status_code == 409, refused.text
    detail = BudgetRefusal.model_validate(refused.json()["detail"])
    assert detail.reason == "budget_slots_exhausted"
    assert detail.limit == 1
    assert detail.consumed == 2
    assert await _launch_count(db_session, world[0]) == before

    rewritten = await _put_policy(
        client,
        auth_headers,
        world[0],
        mode="enforce",
        max_active_launches=1,
        expected_version=approved.json()["version"],
    )
    assert rewritten["approval_status"] == "pending"
    assert rewritten["approved_at"] is None
    assert (await _admit(client, auth_headers, world)).status_code == 201


async def test_enforced_cost_refusal_explains_the_numbers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    world = await _world(client, auth_headers, machine)
    await _enforced(
        client, auth_headers, admin_auth_headers, world[0], cost_limit="1", reservation_cost="0.4"
    )
    for _ in range(2):
        assert (await _admit(client, auth_headers, world)).status_code == 201
    refused = await _admit(client, auth_headers, world)
    assert refused.status_code == 409, refused.text
    detail = BudgetRefusal.model_validate(refused.json()["detail"])
    assert detail.reason == "budget_cost_exhausted"
    assert (detail.consumed, detail.held, detail.requested) == (0, Decimal("0.8"), Decimal("0.4"))
    assert detail.ceiling_guarantee == "admission_only"


async def test_enforced_token_refusal(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    world = await _world(client, auth_headers, machine)
    await _enforced(
        client,
        auth_headers,
        admin_auth_headers,
        world[0],
        token_limit=1000,
        reservation_tokens=600,
    )
    assert (await _admit(client, auth_headers, world)).status_code == 201
    refused = await _admit(client, auth_headers, world)
    assert refused.status_code == 409
    assert refused.json()["detail"]["reason"] == "budget_tokens_exhausted"


async def test_policy_writes_are_versioned_and_validated(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    world = await _world(client, auth_headers, machine)
    url = f"/api/v1/projects/{world[0]}/budget-policy"
    invalid = await client.put(
        url, json={"mode": "enforce", "cost_limit": "1"}, headers=auth_headers
    )
    assert invalid.status_code == 422
    policy = await _put_policy(client, auth_headers, world[0])
    replay = await client.put(url, json={}, headers=auth_headers)
    assert replay.status_code == 200
    assert replay.json()["id"] == policy["id"]
    assert replay.json()["version"] == 1
    duplicate = await client.put(url, json={"period": "day"}, headers=auth_headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == {"error_code": "version_conflict", "server_version": 1}
    stale = await client.put(url, json={"expected_version": 7}, headers=auth_headers)
    assert stale.status_code == 409
    updated = await client.put(
        url, json={"expected_version": policy["version"], "period": "day"}, headers=auth_headers
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    forbidden = await client.put(url, json={}, headers=readonly_auth_headers)
    assert forbidden.status_code == 403


async def test_admission_replay_never_reserves_twice(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    await _put_policy(client, auth_headers, world[0], cost_limit="10", reservation_cost="1")
    key = f"budget-{uuid.uuid4()}"
    first = await _admit(client, auth_headers, world, key=key)
    second = await _admit(client, auth_headers, world, key=key)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    project = uuid.UUID(world[0])
    count = await db_session.scalar(
        select(func.count())
        .select_from(BudgetReservationModel)
        .where(BudgetReservationModel.project_id == project)
    )
    assert count == 1
    admission = await budgets_service.decide_admission(db_session, project, datetime.now(UTC))
    assert admission is not None
    launch_id = uuid.UUID(first.json()["id"])
    row = await budgets_service.record_reservation(db_session, project, launch_id, admission)
    replay = await budgets_service.record_reservation(db_session, project, launch_id, admission)
    assert row.id == replay.id
    assert _meter(await _status(client, auth_headers, world[0]), "cost").held == 1


async def test_measured_usage_replaces_the_reservation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    await _enforced(
        client, auth_headers, admin_auth_headers, world[0], cost_limit="1", reservation_cost="0.6"
    )
    first = (await _admit(client, auth_headers, world)).json()["id"]
    await _finish(db_session, first, ago=timedelta(seconds=5))
    await _usage(db_session, world, first, **_cost("0.1"))
    assert (await _admit(client, auth_headers, world)).status_code == 201
    status = await _status(client, auth_headers, world[0])
    settled = next(r for r in status.reservations if str(r.task_launch_id) == first)
    assert (settled.status, settled.settle_basis) == ("settled", "measured")
    cost = _meter(status, "cost")
    assert (cost.consumed, cost.held) == (Decimal("0.1"), Decimal("0.6"))


async def test_unknown_cost_follows_the_displayed_policy(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    policy = await _enforced(
        client, auth_headers, admin_auth_headers, world[0], cost_limit="1", reservation_cost="0.6"
    )
    assert policy["unknown_cost"] == "charge_reservation"
    first = (await _admit(client, auth_headers, world)).json()["id"]
    await _finish(db_session, first, ago=timedelta(seconds=5))
    await _usage(db_session, world, first, tokens_in=10, tokens_in_coverage="measured")
    refused = await _admit(client, auth_headers, world)
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert (detail["reason"], Decimal(detail["consumed"])) == (
        "budget_cost_exhausted",
        Decimal("0.6"),
    )
    status = await _status(client, auth_headers, world[0])
    assert _meter(status, "cost").unknown_entries == 1

    await _enforced(
        client,
        auth_headers,
        admin_auth_headers,
        world[0],
        cost_limit="1",
        reservation_cost="0.6",
        unknown_cost="ignore",
        expected_version=policy["version"],
    )
    assert (await _admit(client, auth_headers, world)).status_code == 201
    assert _meter(await _status(client, auth_headers, world[0]), "cost").consumed == 0


async def test_late_usage_hold_then_replaced_by_the_measure(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    await _put_policy(
        client,
        auth_headers,
        world[0],
        cost_limit="5",
        reservation_cost="0.6",
        settle_after_seconds=60,
    )
    recent = (await _admit(client, auth_headers, world)).json()["id"]
    late = (await _admit(client, auth_headers, world)).json()["id"]
    await _finish(db_session, recent, ago=timedelta(seconds=5))
    await _finish(db_session, late, ago=timedelta(hours=2))
    reconciled = await client.post(
        f"/api/v1/projects/{world[0]}/budget/reconcile", headers=auth_headers
    )
    assert reconciled.status_code == 200, reconciled.text
    status = BudgetStatus.model_validate(reconciled.json())
    by_launch = {str(r.task_launch_id): r for r in status.reservations}
    assert by_launch[recent].status == "held"
    assert (by_launch[late].status, by_launch[late].settle_basis) == ("settled", "reservation")
    assert status.active_launches == 0
    cost = _meter(status, "cost")
    assert (cost.consumed, cost.held) == (Decimal("0.6"), Decimal("0.6"))

    await _usage(db_session, world, late, **_cost("0.05"))
    cost = _meter(await _status(client, auth_headers, world[0]), "cost")
    assert cost.consumed == Decimal("0.05")


async def test_late_usage_release_charges_nothing_until_reported(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    await _put_policy(
        client,
        auth_headers,
        world[0],
        cost_limit="5",
        reservation_cost="0.6",
        settle_after_seconds=60,
        late_usage="release",
    )
    launch = (await _admit(client, auth_headers, world)).json()["id"]
    await _finish(db_session, launch, ago=timedelta(hours=2))
    status = BudgetStatus.model_validate(
        (
            await client.post(f"/api/v1/projects/{world[0]}/budget/reconcile", headers=auth_headers)
        ).json()
    )
    assert (status.reservations[0].status, status.reservations[0].settle_basis) == (
        "released",
        "none",
    )
    assert _meter(status, "cost").consumed == 0
    await _usage(db_session, world, launch, **_cost("0.2"))
    assert _meter(await _status(client, auth_headers, world[0]), "cost").consumed == Decimal("0.2")


async def test_crash_recovery_frees_slots_and_settles_deterministically(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    await _enforced(
        client,
        auth_headers,
        admin_auth_headers,
        world[0],
        max_active_launches=2,
        cost_limit="10",
        reservation_cost="1",
        settle_after_seconds=60,
    )
    crashed = (await _admit(client, auth_headers, world)).json()["id"]
    unpulled = (await _admit(client, auth_headers, world)).json()["id"]
    assert (await _admit(client, auth_headers, world)).status_code == 409
    past = datetime.now(UTC) - timedelta(hours=2)
    await db_session.execute(
        update(TaskLaunchModel)
        .where(TaskLaunchModel.id == uuid.UUID(crashed))
        .values(status="running", expires_at=past)
    )
    await _finish(
        db_session,
        unpulled,
        ago=timedelta(hours=2),
        status="expired",
        reason_code="expired_unpulled",
    )
    assert (await _status(client, auth_headers, world[0])).active_launches == 0
    url = f"/api/v1/projects/{world[0]}/budget/reconcile"
    first = BudgetStatus.model_validate((await client.post(url, headers=auth_headers)).json())
    replay = BudgetStatus.model_validate((await client.post(url, headers=auth_headers)).json())
    assert first.model_dump() == replay.model_dump()
    by_launch = {str(r.task_launch_id): r for r in first.reservations}
    assert (by_launch[crashed].status, by_launch[crashed].settle_basis) == (
        "settled",
        "reservation",
    )
    assert (by_launch[unpulled].status, by_launch[unpulled].settle_basis) == ("released", "none")
    assert _meter(first, "cost").consumed == 1
    assert (await _admit(client, auth_headers, world)).status_code == 201


async def test_usage_outside_launches_counts_in_the_window(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    await _put_policy(client, auth_headers, world[0], cost_limit="1", reservation_cost="0.1")
    await _usage(db_session, world, None, **_cost("0.95"))
    response = await _admit(client, auth_headers, world)
    assert response.status_code == 201
    status = await _status(client, auth_headers, world[0])
    assert _meter(status, "cost").consumed == Decimal("0.95")
    codes = {a.code.value for a in status.reservations[0].alerts}
    assert "limit_exceeded" in codes
