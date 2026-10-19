"""`usage_ledger_entries` storage (P03 ledger, migration 0031): the SQL
constraints mirror the contract — unknown is NULL never 0, cached tokens never
double counted, deduplicated ingestion on (machine, source event), dated pricing
for an estimated cost — and every entry is scoped to one project."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models import MachineModel, ProjectModel, UsageLedgerEntryModel
from studio_api.services import projects as projects_service

START = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


def _entry(project_id: uuid.UUID, machine_id: uuid.UUID, **fields: Any) -> UsageLedgerEntryModel:
    values: dict[str, Any] = {
        "project_id": project_id,
        "machine_id": machine_id,
        "source_event_id": f"evt-{uuid.uuid4().hex[:12]}",
        "collector": "claude-code-usage",
        "period_start": START,
        "period_end": START + timedelta(minutes=5),
    }
    values.update(fields)
    return UsageLedgerEntryModel(**values)


async def _rejected(db_session: AsyncSession, row: UsageLedgerEntryModel) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(row)
            await db_session.flush()


async def test_unmeasured_metrics_are_stored_as_null_unknown(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    row = _entry(project.id, machine[0].id)
    db_session.add(row)
    await db_session.flush()
    await db_session.refresh(row)
    for metric, coverage in (
        ("tokens_in", "tokens_in_coverage"),
        ("tokens_out", "tokens_out_coverage"),
        ("tokens_cached", "tokens_cached_coverage"),
        ("cost", "cost_coverage"),
        ("duration_seconds", "duration_coverage"),
    ):
        assert getattr(row, metric) is None, metric
        assert getattr(row, coverage) == "unknown", coverage
    assert row.cached_tokens_scope == "included_in_input"
    assert row.version == 1


async def test_sql_refuses_fabricated_or_inconsistent_measures(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    p, m = project.id, machine[0].id
    await _rejected(db_session, _entry(p, m, tokens_in=0))  # value with coverage unknown
    await _rejected(db_session, _entry(p, m, tokens_out_coverage="measured"))  # no value
    await _rejected(db_session, _entry(p, m, tokens_in=-1, tokens_in_coverage="measured"))
    await _rejected(
        db_session,
        _entry(
            p,
            m,
            tokens_in=10,
            tokens_in_coverage="measured",
            tokens_cached=11,
            tokens_cached_coverage="measured",
        ),
    )
    await _rejected(db_session, _entry(p, m, cached_tokens_scope="both"))
    await _rejected(
        db_session, _entry(p, m, cost=Decimal("1"), cost_coverage="measured")
    )  # no currency
    await _rejected(
        db_session,
        _entry(p, m, cost=Decimal("1"), cost_coverage="estimated", cost_currency="EUR"),
    )  # estimated without a dated price list
    await _rejected(db_session, _entry(p, m, price_list_id="p1", price_effective_from=START))
    await _rejected(db_session, _entry(p, m, period_end=START - timedelta(seconds=1)))


async def test_cost_with_currency_and_dated_pricing_is_accepted(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    row = _entry(
        project.id,
        machine[0].id,
        tokens_in=1000,
        tokens_in_coverage="measured",
        tokens_cached=1500,
        tokens_cached_coverage="measured",
        cached_tokens_scope="additional_to_input",
        cost=Decimal("0.01234567"),
        cost_coverage="estimated",
        cost_currency="USD",
        price_list_id="anthropic-2026-10",
        price_effective_from=START - timedelta(days=10),
        model="anthropic/claude-opus-4-5[1m]",
    )
    db_session.add(row)
    await db_session.flush()
    await db_session.refresh(row)
    assert row.cost == Decimal("0.01234567")


async def test_ingestion_is_deduplicated_per_machine_and_source_event(
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    db_session.add(_entry(project.id, machine[0].id, source_event_id="evt-1"))
    await db_session.flush()
    await _rejected(db_session, _entry(project.id, machine[0].id, source_event_id="evt-1"))
    db_session.add(_entry(project.id, other_machine[0].id, source_event_id="evt-1"))
    await db_session.flush()


async def test_entries_are_isolated_per_project(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    other = await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Other Project", None, creator=None
    )
    mine = _entry(project.id, machine[0].id)
    theirs = _entry(other.id, machine[0].id)
    db_session.add_all([mine, theirs])
    await db_session.flush()
    rows = (
        await db_session.scalars(
            select(UsageLedgerEntryModel).where(UsageLedgerEntryModel.project_id == project.id)
        )
    ).all()
    assert [r.id for r in rows] == [mine.id]
    await _rejected(db_session, _entry(uuid.uuid4(), machine[0].id))  # unknown project
