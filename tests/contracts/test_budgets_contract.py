"""Budget policy contract shapes (P03-budgets): alert-only by default, an
enforced limit needs a positive per-launch reservation, refusals and alerts use
closed vocabularies. No DB, no app."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from studio_contracts.budgets import (
    BudgetAlertCode,
    BudgetMetric,
    BudgetMode,
    BudgetPolicyUpdate,
    BudgetRefusal,
    BudgetRefusalReason,
    BudgetStatus,
    CeilingGuarantee,
    LateUsagePolicy,
    UnknownCostPolicy,
)


def test_defaults_are_alert_only_and_conservative() -> None:
    policy = BudgetPolicyUpdate()
    assert policy.mode is BudgetMode.ALERT_ONLY
    assert policy.unknown_cost is UnknownCostPolicy.CHARGE_RESERVATION
    assert policy.late_usage is LateUsagePolicy.HOLD_RESERVATION
    assert policy.alert_thresholds == [80, 100]
    assert policy.expected_version is None


def test_alert_only_accepts_a_limit_without_reservation() -> None:
    assert BudgetPolicyUpdate(cost_limit=Decimal("5")).reservation_cost is None


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "enforce"},
        {"mode": "enforce", "cost_limit": "5"},
        {"mode": "enforce", "cost_limit": "5", "reservation_cost": "0"},
        {"mode": "enforce", "token_limit": 1000},
        {"alert_thresholds": [0]},
        {"alert_thresholds": [80, 80]},
        {"alert_thresholds": [101]},
        {"max_active_launches": 0},
        {"cost_limit": "-1"},
        {"unknown": "field"},
    ],
)
def test_invalid_policies_are_rejected(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BudgetPolicyUpdate.model_validate(body)


def test_enforce_with_slots_only_is_valid_and_thresholds_sorted() -> None:
    policy = BudgetPolicyUpdate.model_validate(
        {"mode": "enforce", "max_active_launches": 2, "alert_thresholds": [100, 50]}
    )
    assert policy.alert_thresholds == [50, 100]


def test_refusal_has_a_stable_reason_and_never_promises_a_ceiling() -> None:
    refusal = BudgetRefusal(
        reason=BudgetRefusalReason.SLOTS_EXHAUSTED,
        metric=BudgetMetric.SLOTS,
        limit=Decimal(2),
        consumed=Decimal(2),
        held=Decimal(0),
        requested=Decimal(1),
    )
    dumped = refusal.model_dump(mode="json")
    assert dumped["error_code"] == "budget_refused"
    assert dumped["reason"] == "budget_slots_exhausted"
    assert dumped["ceiling_guarantee"] == CeilingGuarantee.ADMISSION_ONLY.value
    assert {r.value for r in BudgetRefusalReason} == {
        "budget_cost_exhausted",
        "budget_tokens_exhausted",
        "budget_slots_exhausted",
    }
    assert {c.value for c in BudgetAlertCode} == {
        "threshold_reached",
        "limit_exceeded",
        "slots_exhausted",
        "unknown_usage",
        "enforce_pending_approval",
    }


def test_status_without_policy_guarantees_nothing() -> None:
    from uuid import uuid4

    status = BudgetStatus(project_id=uuid4())
    assert status.effective_mode is BudgetMode.ALERT_ONLY
    assert status.ceiling_guarantee is CeilingGuarantee.NONE
    assert status.meters == []
