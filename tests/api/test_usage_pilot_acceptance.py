from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_client.usage.collectors import CollectorRegistry, RunObservation
from studio_client.usage.recorder import build_launch_entry
from studio_contracts.task_launch import TaskLaunch
from studio_contracts.usage import MeasurementCoverage, UsageLedgerEntry, UsageTotalStatus

from tests.api.test_budgets import _admit, _finish, _meter, _put_policy, _status, _world
from tests.api.test_usage import _post
from tests.api.test_usage_summary import _ledger, _summary

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "usage" / "claude_code" / "2.1.287"


async def test_archived_pilot_outputs_reconcile_ledger_summary_and_budget_after_replay(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    world = await _world(client, auth_headers, machine)
    project_id = uuid.UUID(world[0])
    await _put_policy(client, auth_headers, world[0], cost_limit="1", reservation_cost="0.6")
    launch_ids: set[uuid.UUID] = set()
    for filename, duration in (("success.json", "10.383"), ("success_cache_read.json", "8.218")):
        admitted = await _admit(client, auth_headers, world)
        assert admitted.status_code == 201, admitted.text
        launch = TaskLaunch.model_validate(admitted.json())
        launch_ids.add(launch.id)
        start = datetime.now(UTC)
        run = RunObservation(
            harness_id="claude-code",
            output=(FIXTURES / filename).read_text(encoding="utf-8"),
            truncated=False,
            exit_code=0,
            timed_out=False,
            cancelled=False,
            started_at=start,
            finished_at=start + timedelta(seconds=float(duration)),
            duration_seconds=float(duration),
        )
        collected = CollectorRegistry().collect(run)
        assert collected.diagnostics == ()
        body = build_launch_entry(launch, run, collected).model_dump(mode="json")
        key = str(uuid.uuid4())
        created = await _post(client, auth_headers, body, key=key)
        assert created.status_code == 201, created.text
        stored = UsageLedgerEntry.model_validate(created.json())
        assert stored.task_launch_id == launch.id
        assert stored.provenance.collector == collected.collector
        assert stored.provenance.model == collected.model
        assert stored.provenance.provider == collected.provider
        assert stored.provenance.collector_version == collected.collector_version
        assert stored.tokens_in == collected.metrics.tokens_in
        assert stored.tokens_out == collected.metrics.tokens_out
        assert stored.tokens_cached == collected.metrics.tokens_cached
        assert stored.total_tokens == collected.metrics.total_tokens
        assert stored.cost.value is not None and collected.metrics.cost.value is not None
        assert stored.cost.value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP) == (
            collected.metrics.cost.value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        )
        assert stored.cost.currency == "USD"
        assert stored.cost.coverage is MeasurementCoverage.MEASURED
        assert stored.duration == collected.metrics.duration
        for replay_key in (key, str(uuid.uuid4())):
            replay = await _post(client, auth_headers, body, key=replay_key)
            assert replay.status_code == 201, replay.text
            assert replay.json()["id"] == str(stored.id)
            assert replay.json()["version"] == stored.version
        await _finish(db_session, str(launch.id), ago=timedelta(seconds=5))

    reconcile_url = f"/api/v1/projects/{world[0]}/budget/reconcile"
    reconciled = await client.post(reconcile_url, headers=auth_headers)
    assert reconciled.status_code == 200, reconciled.text
    replayed = await client.post(reconcile_url, headers=auth_headers)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == reconciled.json()

    ledger = await _ledger(client, auth_headers, project_id)
    summary = (await _summary(client, auth_headers, project_id)).total
    assert summary.entries == len(ledger) == 2
    assert {entry.task_launch_id for entry in ledger} == launch_ids
    assert summary.tokens_in.known_sum == 4
    assert summary.tokens_out.known_sum == 8
    assert summary.tokens_cached.known_sum == 68083
    assert summary.total_tokens.known_sum == 68095
    assert summary.total_tokens.status is UsageTotalStatus.EXACT
    assert summary.cost.known_sum == Decimal("0.36400480")
    assert summary.cost.status is UsageTotalStatus.EXACT
    assert summary.cost.currency == "USD"
    assert summary.cost.measured_entries == 2
    assert summary.cost.estimated_entries == summary.cost.unknown_entries == 0
    assert summary.duration.known_sum == Decimal("18.601")
    assert summary.duration.status is UsageTotalStatus.EXACT
    assert summary.cost.known_sum == sum(
        (entry.cost.value for entry in ledger if entry.cost.value is not None), Decimal(0)
    )
    budget = await _status(client, auth_headers, world[0])
    assert _meter(budget, "cost").consumed == summary.cost.known_sum
    assert _meter(budget, "cost").held == 0
    assert {reservation.task_launch_id for reservation in budget.reservations} == launch_ids
    assert all(
        reservation.status == "settled" and reservation.settle_basis == "measured"
        for reservation in budget.reservations
    )
