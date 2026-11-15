from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_contracts.usage import (
    CostBasis,
    UsageSubscription,
    UsageSummary,
    UsageTotalStatus,
)

from tests.api.test_usage import START, _entry, _post
from tests.api.test_usage_summary import _task

SUBSCRIPTIONS = "/api/v1/usage/subscriptions"


def _usage(
    project_id: uuid.UUID,
    machine_id: uuid.UUID,
    harness: str,
    cost: str | None,
    *,
    at: datetime = START,
    currency: str = "USD",
    task_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    changes: dict[str, Any] = {
        "provenance": {"collector": "runtime", "harness": harness},
        "period_start": at.isoformat(),
        "period_end": (at + timedelta(seconds=5)).isoformat(),
    }
    if cost is not None:
        changes["cost"] = {"value": cost, "coverage": "measured", "currency": currency}
    if task_id is not None:
        changes["task_id"] = str(task_id)
    return _entry(project_id, machine_id, **changes)


async def _summary(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID, **params: str
) -> UsageSummary:
    response = await client.get(
        "/api/v1/usage/summary",
        headers=headers,
        params={"project_id": str(project_id), **params},
    )
    assert response.status_code == 200, response.text
    return UsageSummary.model_validate(response.json())


async def test_subscription_price_is_split_pro_rata_at_read_time(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, machine_id = project.id, machine[0].id
    first = await _task(db_session, project_id, "Première")
    second = await _task(db_session, project_id, "Seconde")
    created = await client.post(
        SUBSCRIPTIONS,
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project_id),
            "label": "Claude Max",
            "monthly_price": "100.00",
            "currency": "EUR",
            "harnesses": ["claude-code"],
            "starts_on": "2026-09-01",
        },
    )
    assert created.status_code == 201, created.text
    subscription = UsageSubscription.model_validate(created.json())

    september = datetime(2026, 9, 5, tzinfo=UTC)
    now = datetime.now(UTC)
    for body in (
        _usage(project_id, machine_id, "claude-code", "3", task_id=first),
        _usage(project_id, machine_id, "claude-code", "1", task_id=second),
        _usage(project_id, machine_id, "codex", "5", task_id=first),
        _usage(project_id, machine_id, "claude-code", None, task_id=second),
        _usage(project_id, machine_id, "claude-code", "2", at=september),
        _usage(project_id, machine_id, "claude-code", "1", at=september, currency="EUR"),
        _usage(project_id, machine_id, "claude-code", "2", at=now - timedelta(minutes=1)),
    ):
        response = await _post(client, auth_headers, body)
        assert response.status_code == 201, response.text

    october = {"since": "2026-10-01T00:00:00Z", "until": "2026-11-01T00:00:00Z"}
    summary = await _summary(client, auth_headers, project_id, group_by="task", **october)
    assert summary.total.cost.bases == [CostBasis.API_EQUIVALENT]
    share = summary.total.subscription_share
    assert share is not None
    assert share.basis is CostBasis.SUBSCRIPTION_SHARE
    assert (share.status, share.known_sum, share.currency) == (
        UsageTotalStatus.PARTIAL,
        Decimal("100"),
        "EUR",
    )
    assert (share.estimated_entries, share.unknown_entries, share.provisional) == (2, 1, False)
    by_task = {group.key.task_id: group.subscription_share for group in summary.groups}
    assert by_task[first] is not None and by_task[first].known_sum == Decimal("75")
    assert by_task[second] is not None and by_task[second].known_sum == Decimal("25")
    assert by_task[second].status is UsageTotalStatus.PARTIAL

    scoped = await _summary(client, auth_headers, project_id, task_id=str(first), **october)
    assert scoped.total.subscription_share is not None
    assert scoped.total.subscription_share.known_sum == Decimal("75")

    mixed = await _summary(
        client,
        auth_headers,
        project_id,
        since="2026-09-01T00:00:00Z",
        until="2026-10-01T00:00:00Z",
    )
    assert mixed.total.subscription_share is not None
    assert mixed.total.subscription_share.status is UsageTotalStatus.UNKNOWN
    assert mixed.total.subscription_share.unknown_entries == 2

    current = await _summary(
        client,
        auth_headers,
        project_id,
        since=datetime(now.year, now.month, 1, tzinfo=UTC).isoformat(),
    )
    assert current.total.subscription_share is not None
    assert current.total.subscription_share.known_sum == Decimal("100")
    assert current.total.subscription_share.provisional is True

    terms = {
        "label": "Claude Max 20x",
        "monthly_price": "200.00",
        "currency": "EUR",
        "harnesses": ["claude-code"],
        "starts_on": "2026-09-01",
    }
    conflict = await client.put(
        f"{SUBSCRIPTIONS}/{subscription.id}",
        headers=auth_headers,
        json={**terms, "expected_version": 2},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"error_code": "version_conflict", "server_version": 1}
    updated = await client.put(
        f"{SUBSCRIPTIONS}/{subscription.id}",
        headers=auth_headers,
        json={**terms, "expected_version": 1},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    listed = await client.get(
        SUBSCRIPTIONS, headers=auth_headers, params={"project_id": str(project_id)}
    )
    assert [item["label"] for item in listed.json()] == ["Claude Max 20x"]
    doubled = await _summary(client, auth_headers, project_id, **october)
    assert doubled.total.subscription_share is not None
    assert doubled.total.subscription_share.known_sum == Decimal("200")

    deleted = await client.delete(
        f"{SUBSCRIPTIONS}/{subscription.id}",
        headers=auth_headers,
        params={"expected_version": 2},
    )
    assert deleted.status_code == 204
    after = await _summary(client, auth_headers, project_id, **october)
    assert after.total.subscription_share is None


async def test_recorded_basis_round_trips_and_shows_on_totals(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    project_id, machine_id = project.id, machine[0].id
    billed = _usage(project_id, machine_id, "claude-code", "2")
    billed["cost"]["basis"] = "measured_billed"
    response = await _post(client, auth_headers, billed)
    assert response.status_code == 201, response.text
    assert response.json()["cost"]["basis"] == "measured_billed"
    legacy = await _post(client, auth_headers, _usage(project_id, machine_id, "codex", "1"))
    assert legacy.json()["cost"]["basis"] == "api_equivalent"
    unknown = await _post(client, auth_headers, _usage(project_id, machine_id, "codex", None))
    assert unknown.json()["cost"]["basis"] is None
    summary = await _summary(client, auth_headers, project_id)
    assert summary.total.cost.bases == [CostBasis.API_EQUIVALENT, CostBasis.MEASURED_BILLED]
    assert summary.total.subscription_share is None


async def test_estimate_on_a_mislabelled_eur_grid_is_stored_as_usd(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    pricing = {"price_list_id": "public-eur-2026-11", "effective_from": "2026-11-03T00:00:00Z"}
    body = _entry(
        project.id,
        machine[0].id,
        cost={"value": "0.5", "coverage": "estimated", "currency": "EUR"},
        pricing=pricing,
    )
    created = await _post(client, auth_headers, body)
    assert created.status_code == 201, created.text
    assert created.json()["cost"]["currency"] == "USD"
    custom = _entry(
        project.id,
        machine[0].id,
        cost={"value": "0.5", "coverage": "estimated", "currency": "EUR"},
        pricing={**pricing, "price_list_id": "perso-eur"},
    )
    kept = await _post(client, auth_headers, custom)
    assert kept.json()["cost"]["currency"] == "EUR"
