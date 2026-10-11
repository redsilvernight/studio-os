"""`UsageLedgerEntry` contract shapes (P03 ledger): an absent measure is `None` +
`unknown`, never a fabricated zero; cached tokens are never double counted;
coverage is per metric; cost needs a currency and, when estimated, a dated price
list; corrections cannot move an entry. No DB, no app."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from studio_contracts.usage import (
    CacheTokenScope,
    CostMeasurement,
    DurationMeasurement,
    MeasurementCoverage,
    TokenMeasurement,
    UsageLedgerCorrection,
    UsageLedgerEntry,
    UsageLedgerEntryCreate,
    UsageMetrics,
    UsageProvenance,
)

START = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
PRICING = {"price_list_id": "anthropic-2026-10", "effective_from": "2026-10-01T00:00:00Z"}


def _measured(value: int) -> dict[str, Any]:
    return {"value": value, "coverage": "measured"}


def _create(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": str(uuid4()),
        "machine_id": str(uuid4()),
        "source_event_id": "claude-code:session-1:turn-3",
        "provenance": {
            "collector": "claude-code-usage",
            "collector_version": "0.1.0",
            "harness": "claude-code",
            "harness_version": "2.1.0",
            "provider": "anthropic",
            "model": "anthropic/claude-opus-4-5[1m]",
        },
        "period_start": START.isoformat(),
        "period_end": (START + timedelta(minutes=5)).isoformat(),
    }
    payload.update(overrides)
    return payload


# --- absent values: None + unknown, never 0 --------------------------------


def test_default_entry_is_entirely_unknown_never_zero() -> None:
    entry = UsageLedgerEntryCreate.model_validate(_create())
    for name, coverage in entry.coverage_by_metric.items():
        assert coverage is MeasurementCoverage.UNKNOWN, name
        assert getattr(entry, name).value is None, name
    assert entry.total_tokens is None
    dumped = entry.model_dump(mode="json")
    assert dumped["tokens_in"] == {"value": None, "coverage": "unknown", "unit": "tokens"}
    assert dumped["cost"]["value"] is None and dumped["cost"]["currency"] is None


def test_measured_zero_is_distinct_from_unknown() -> None:
    zero = TokenMeasurement(value=0, coverage=MeasurementCoverage.MEASURED)
    assert zero.value == 0
    assert zero != TokenMeasurement()


@pytest.mark.parametrize("coverage", ["measured", "estimated"])
def test_known_coverage_requires_a_value(coverage: str) -> None:
    with pytest.raises(ValidationError):
        TokenMeasurement.model_validate({"value": None, "coverage": coverage})


def test_unknown_coverage_refuses_a_value() -> None:
    with pytest.raises(ValidationError):
        TokenMeasurement.model_validate({"value": 0, "coverage": "unknown"})


@pytest.mark.parametrize("model", [TokenMeasurement, DurationMeasurement, CostMeasurement])
def test_negative_measures_are_refused(model: type[Any]) -> None:
    payload: dict[str, Any] = {"value": -1, "coverage": "measured"}
    if model is CostMeasurement:
        payload["currency"] = "EUR"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_unit_is_fixed_by_the_field() -> None:
    with pytest.raises(ValidationError):
        TokenMeasurement.model_validate({"value": 1, "coverage": "measured", "unit": "seconds"})


def test_coverage_is_closed() -> None:
    with pytest.raises(ValidationError):
        TokenMeasurement.model_validate({"value": 1, "coverage": "guessed"})


# --- coverage per metric ----------------------------------------------------


def test_coverage_is_reported_per_metric() -> None:
    entry = UsageLedgerEntryCreate.model_validate(
        _create(
            tokens_in=_measured(1200),
            tokens_out={"value": 300, "coverage": "estimated"},
            duration={"value": "12.5", "coverage": "measured"},
        )
    )
    assert entry.coverage_by_metric == {
        "tokens_in": MeasurementCoverage.MEASURED,
        "tokens_out": MeasurementCoverage.ESTIMATED,
        "tokens_cached": MeasurementCoverage.UNKNOWN,
        "cost": MeasurementCoverage.UNKNOWN,
        "duration": MeasurementCoverage.MEASURED,
    }
    assert entry.duration.value == Decimal("12.5")


# --- cached tokens: counted apart, never twice ------------------------------


def test_cached_included_in_input_is_not_added_again() -> None:
    metrics = UsageMetrics(
        tokens_in=TokenMeasurement(value=1000, coverage=MeasurementCoverage.MEASURED),
        tokens_out=TokenMeasurement(value=200, coverage=MeasurementCoverage.MEASURED),
        tokens_cached=TokenMeasurement(value=800, coverage=MeasurementCoverage.MEASURED),
        cached_tokens_scope=CacheTokenScope.INCLUDED_IN_INPUT,
    )
    assert metrics.total_tokens == 1200


def test_cached_additional_to_input_is_added_once() -> None:
    metrics = UsageMetrics(
        tokens_in=TokenMeasurement(value=200, coverage=MeasurementCoverage.MEASURED),
        tokens_out=TokenMeasurement(value=200, coverage=MeasurementCoverage.MEASURED),
        tokens_cached=TokenMeasurement(value=800, coverage=MeasurementCoverage.MEASURED),
        cached_tokens_scope=CacheTokenScope.ADDITIONAL_TO_INPUT,
    )
    assert metrics.total_tokens == 1200


def test_unknown_cache_does_not_hide_a_total_it_is_already_inside() -> None:
    metrics = UsageMetrics(
        tokens_in=TokenMeasurement(value=1000, coverage=MeasurementCoverage.MEASURED),
        tokens_out=TokenMeasurement(value=200, coverage=MeasurementCoverage.MEASURED),
    )
    assert metrics.total_tokens == 1200
    additional = metrics.model_copy(
        update={"cached_tokens_scope": CacheTokenScope.ADDITIONAL_TO_INPUT}
    )
    assert additional.total_tokens is None


def test_partial_total_is_never_fabricated() -> None:
    metrics = UsageMetrics(
        tokens_in=TokenMeasurement(value=1000, coverage=MeasurementCoverage.MEASURED)
    )
    assert metrics.total_tokens is None


def test_included_cache_cannot_exceed_input() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        UsageMetrics.model_validate({"tokens_in": _measured(100), "tokens_cached": _measured(101)})
    UsageMetrics.model_validate(
        {
            "tokens_in": _measured(100),
            "tokens_cached": _measured(101),
            "cached_tokens_scope": "additional_to_input",
        }
    )


# --- cost, currency and dated pricing ---------------------------------------


def test_cost_requires_currency_and_currency_requires_cost() -> None:
    with pytest.raises(ValidationError):
        CostMeasurement.model_validate({"value": "1.5", "coverage": "estimated"})
    with pytest.raises(ValidationError):
        CostMeasurement.model_validate({"coverage": "unknown", "currency": "EUR"})
    with pytest.raises(ValidationError):
        CostMeasurement.model_validate({"value": "1", "coverage": "measured", "currency": "eur"})


def test_estimated_cost_requires_a_dated_price_list() -> None:
    cost = {"value": "0.42", "coverage": "estimated", "currency": "USD"}
    with pytest.raises(ValidationError, match="price list"):
        UsageLedgerEntryCreate.model_validate(_create(cost=cost))
    entry = UsageLedgerEntryCreate.model_validate(_create(cost=cost, pricing=PRICING))
    assert entry.pricing is not None
    assert entry.pricing.effective_from == datetime(2026, 10, 1, tzinfo=UTC)


def test_measured_cost_may_omit_pricing() -> None:
    cost = {"value": "0.42", "coverage": "measured", "currency": "USD"}
    assert UsageLedgerEntryCreate.model_validate(_create(cost=cost)).pricing is None


def test_pricing_without_cost_is_refused() -> None:
    with pytest.raises(ValidationError):
        UsageLedgerEntryCreate.model_validate(_create(pricing=PRICING))


def test_pricing_date_must_be_timezone_aware() -> None:
    cost = {"value": "0.42", "coverage": "estimated", "currency": "USD"}
    naive = {"price_list_id": "p1", "effective_from": "2026-10-01T00:00:00"}
    with pytest.raises(ValidationError):
        UsageLedgerEntryCreate.model_validate(_create(cost=cost, pricing=naive))


# --- identity, provenance, period -------------------------------------------


def test_period_must_not_be_reversed_nor_naive() -> None:
    with pytest.raises(ValidationError, match="precedes"):
        UsageLedgerEntryCreate.model_validate(
            _create(period_end=(START - timedelta(seconds=1)).isoformat())
        )
    with pytest.raises(ValidationError):
        UsageLedgerEntryCreate.model_validate(_create(period_start="2026-10-11T09:00:00"))


def test_project_machine_source_and_collector_are_required() -> None:
    for field in ("project_id", "machine_id", "source_event_id", "provenance"):
        payload = _create()
        del payload[field]
        with pytest.raises(ValidationError):
            UsageLedgerEntryCreate.model_validate(payload)


@pytest.mark.parametrize("bad", ["", "a b", "../etc/passwd", "x" * 129, "-leading"])
def test_source_event_id_is_a_bounded_token(bad: str) -> None:
    with pytest.raises(ValidationError):
        UsageLedgerEntryCreate.model_validate(_create(source_event_id=bad))


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        UsageLedgerEntryCreate.model_validate(_create(total_tokens=0))


def test_stored_entry_is_versioned() -> None:
    now = datetime.now(UTC)
    entry = UsageLedgerEntry.model_validate(
        {**_create(), "id": str(uuid4()), "version": 1, "created_at": now, "updated_at": now}
    )
    assert entry.version == 1


def test_correction_cannot_move_the_entry() -> None:
    base = {
        "machine_id": str(uuid4()),
        "source_event_id": "evt-1",
        "expected_version": 1,
        "provenance": {"collector": "claude-code-usage"},
        "period_start": START.isoformat(),
        "period_end": START.isoformat(),
        "tokens_in": _measured(10),
    }
    correction = UsageLedgerCorrection.model_validate(base)
    assert correction.tokens_in.value == 10
    for moved in ("project_id", "session_id", "task_launch_id", "ai_work_id", "task_id"):
        with pytest.raises(ValidationError):
            UsageLedgerCorrection.model_validate({**base, moved: str(uuid4())})
    with pytest.raises(ValidationError):
        UsageLedgerCorrection.model_validate({**base, "expected_version": 0})


def test_schema_descriptions_carry_no_decision_number() -> None:
    for model in (UsageLedgerEntryCreate, UsageLedgerEntry, UsageLedgerCorrection, UsageProvenance):
        assert not re.search(r"DEC-\d", json.dumps(model.model_json_schema())), model.__name__
