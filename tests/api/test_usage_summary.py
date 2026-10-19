from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_contracts.usage import UsageLedgerEntry, UsageSummary, UsageTotalStatus

from tests.api.test_launch_credentials import _accepted_launch, _credential
from tests.api.test_usage import START, _correction, _entry, _post

SUMMARY = "/api/v1/usage/summary"


def _measured(value: int | str) -> dict[str, Any]:
    return {"value": value, "coverage": "measured"}


def _cost(value: str, currency: str = "USD") -> dict[str, Any]:
    return {"value": value, "coverage": "measured", "currency": currency}


async def _summary(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID, **params: str
) -> UsageSummary:
    response = await client.get(
        SUMMARY, headers=headers, params={"project_id": str(project_id), **params}
    )
    assert response.status_code == 200, response.text
    return UsageSummary.model_validate(response.json())


async def _ledger(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID
) -> list[UsageLedgerEntry]:
    response = await client.get(
        "/api/v1/usage", headers=headers, params={"project_id": str(project_id), "limit": 500}
    )
    assert response.status_code == 200, response.text
    return [UsageLedgerEntry.model_validate(item) for item in response.json()]


async def _task(db_session: AsyncSession, project_id: uuid.UUID, title: str) -> uuid.UUID:
    task = TaskModel(project_id=project_id, title=title)
    db_session.add(task)
    await db_session.flush()
    return task.id


async def test_summary_equals_ledger_after_replays_and_cumulative_corrections(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, machine_id = project.id, machine[0].id
    task_id = await _task(db_session, project_id, "Afficher le coût")
    claude = {"collector": "studio-claude-code", "harness": "claude-code", "model": "opus"}
    snapshot = _entry(
        project_id,
        machine_id,
        task_id=str(task_id),
        provenance=claude,
        tokens_in=_measured(10),
        tokens_out=_measured(2),
        tokens_cached=_measured(100),
        cached_tokens_scope="additional_to_input",
        cost=_cost("0.05"),
        duration=_measured("3.5"),
    )
    created = await _post(client, auth_headers, snapshot, key=str(uuid.uuid4()))
    assert created.status_code == 201, created.text
    for _ in range(3):
        replay = await _post(
            client,
            auth_headers,
            {**snapshot, "tokens_in": _measured(999), "cost": _cost("9.99")},
            key=str(uuid.uuid4()),
        )
        assert replay.status_code == 201, replay.text
    final = _correction(
        created.json(),
        provenance=claude,
        tokens_in=_measured(25),
        tokens_out=_measured(5),
        tokens_cached=_measured(300),
        cached_tokens_scope="additional_to_input",
        cost=_cost("0.125"),
        duration=_measured("12.25"),
    )
    corrected = await _post(client, auth_headers, final, key=str(uuid.uuid4()), correction=True)
    assert corrected.status_code == 200, corrected.text
    replayed_final = await _post(
        client, auth_headers, final, key=str(uuid.uuid4()), correction=True
    )
    assert replayed_final.status_code == 409
    runner = _entry(
        project_id,
        machine_id,
        task_id=str(task_id),
        provenance={"collector": "studio-runner", "harness": "codex"},
        duration=_measured("4.75"),
    )
    assert (await _post(client, auth_headers, runner)).status_code == 201
    assert (await _post(client, auth_headers, runner)).status_code == 201

    summary = await _summary(client, auth_headers, project_id)
    ledger = await _ledger(client, auth_headers, project_id)
    assert summary.total.entries == len(ledger) == 2
    known_tokens = [e.total_tokens for e in ledger if e.total_tokens is not None]
    assert summary.total.total_tokens.known_sum == sum(known_tokens) == 330
    assert summary.total.total_tokens.status is UsageTotalStatus.PARTIAL
    assert summary.total.tokens_in.known_sum == 25
    durations = [e.duration.value for e in ledger if e.duration.value is not None]
    assert summary.total.duration.known_sum == sum(durations, Decimal(0)) == Decimal("17")
    assert summary.total.duration.status is UsageTotalStatus.EXACT
    assert summary.total.cost.status is UsageTotalStatus.PARTIAL
    assert summary.total.cost.known_sum == Decimal("0.125")
    assert summary.total.cost.currency == "USD"
    assert summary.total.cost.unknown_entries == 1
    assert [(s.collector, s.entries) for s in summary.total.sources] == [
        ("studio-claude-code", 1),
        ("studio-runner", 1),
    ]

    for group_by in ("task", "configuration", "day"):
        grouped = await _summary(client, auth_headers, project_id, group_by=group_by)
        assert grouped.total == summary.total
        assert sum(g.entries for g in grouped.groups) == summary.total.entries
        assert (
            sum(g.duration.known_sum or Decimal(0) for g in grouped.groups)
            == summary.total.duration.known_sum
        )
    by_task = await _summary(client, auth_headers, project_id, group_by="task")
    assert [(g.key.task_id, g.key.task_title) for g in by_task.groups] == [
        (task_id, "Afficher le coût")
    ]
    by_config = await _summary(client, auth_headers, project_id, group_by="configuration")
    configs = {(g.key.harness, g.key.model): g for g in by_config.groups}
    assert configs[("claude-code", "opus")].cost.status is UsageTotalStatus.EXACT
    assert configs[("codex", None)].cost.status is UsageTotalStatus.UNKNOWN
    assert configs[("codex", None)].cost.known_sum is None
    by_day = await _summary(client, auth_headers, project_id, group_by="day")
    assert [g.key.day for g in by_day.groups] == [START.date()]


async def test_mixed_currencies_and_estimates_are_never_an_exact_total(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    project_id, machine_id = project.id, machine[0].id
    pricing = {"price_list_id": "prices-v1", "effective_from": START.isoformat()}
    usd = _entry(project_id, machine_id, cost=_cost("1.50"))
    estimated = _entry(
        project_id,
        machine_id,
        cost={"value": "0.50", "coverage": "estimated", "currency": "USD"},
        pricing=pricing,
    )
    for body in (usd, estimated):
        assert (await _post(client, auth_headers, body)).status_code == 201
    only_usd = await _summary(client, auth_headers, project_id)
    assert only_usd.total.cost.status is UsageTotalStatus.ESTIMATED
    assert only_usd.total.cost.known_sum == Decimal("2.00")

    eur = _entry(project_id, machine_id, cost=_cost("3", "EUR"))
    assert (await _post(client, auth_headers, eur)).status_code == 201
    mixed = await _summary(client, auth_headers, project_id)
    assert mixed.total.cost.status is UsageTotalStatus.MIXED_CURRENCY
    assert mixed.total.cost.known_sum is None and mixed.total.cost.currency is None
    assert [(c.currency, c.known_sum, c.entries) for c in mixed.total.cost.by_currency] == [
        ("EUR", Decimal("3"), 1),
        ("USD", Decimal("2.00"), 2),
    ]
    assert mixed.total.tokens_in.status is UsageTotalStatus.UNKNOWN
    assert mixed.total.tokens_in.known_sum is None


async def test_period_task_filters_empty_scope_and_access(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, machine_id = project.id, machine[0].id
    task_id = await _task(db_session, project_id, "Filtrée")
    later = START + timedelta(days=2)
    bodies = [
        _entry(project_id, machine_id, task_id=str(task_id), duration=_measured("1")),
        _entry(
            project_id,
            machine_id,
            duration=_measured("2"),
            period_start=later.isoformat(),
            period_end=(later + timedelta(seconds=2)).isoformat(),
        ),
    ]
    for body in bodies:
        assert (await _post(client, auth_headers, body)).status_code == 201
    of_task = await _summary(client, auth_headers, project_id, task_id=str(task_id))
    assert of_task.total.entries == 1 and of_task.total.duration.known_sum == Decimal("1")
    recent = await _summary(
        client, auth_headers, project_id, since=(START + timedelta(days=1)).isoformat()
    )
    assert recent.total.duration.known_sum == Decimal("2")
    empty = await _summary(
        client, auth_headers, project_id, until=(START - timedelta(days=1)).isoformat()
    )
    assert empty.total.entries == 0
    assert empty.total.cost.status is UsageTotalStatus.NONE
    assert empty.total.duration.known_sum is None
    by_task = await _summary(client, auth_headers, project_id, group_by="task")
    assert {g.key.task_title for g in by_task.groups} == {"Filtrée", None}

    inverted = await client.get(
        SUMMARY,
        headers=auth_headers,
        params={
            "project_id": str(project_id),
            "since": later.isoformat(),
            "until": START.isoformat(),
        },
    )
    assert inverted.status_code == 422
    assert inverted.json()["detail"]["error_code"] == "invalid_usage_period"
    assert (await client.get(SUMMARY, headers=auth_headers)).status_code == 422


async def test_launch_credential_cannot_read_summary(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    project_id, launch_id, _ = await _accepted_launch(client, auth_headers, machine)
    ephemeral = await _credential(client, auth_headers, launch_id)
    response = await client.get(SUMMARY, headers=ephemeral, params={"project_id": project_id})
    assert response.status_code == 403
