"""Launch budgets and admission (Mission Control P03-budgets, additive).

A project may declare one explicit budget policy. Every TaskLaunch admission
reserves the policy's fixed per-launch amount under a PostgreSQL row lock, so
two simultaneous admissions never share a reservation nor exceed the admitted
slots. Usage is only reported after a run (DEC-0197), so a budget never
guarantees a spending ceiling: in `enforce` mode it bounds what is *admitted*
(reservations), never what a run actually consumes. `alert_only` — the
default — admits everything and only records alerts.

Refusals use the closed vocabulary `BudgetRefusalReason`; alerts use
`BudgetAlertCode`. Stable tokens, never free text. Activating `enforce` (a
policy able to stop new work) needs an explicit admin approval: until then the
effective mode stays `alert_only`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from studio_contracts.common import ContractModel, VersionedModel
from studio_contracts.usage import CurrencyCode

BUDGET_MAX_COST = Decimal("9999999999.99999999")
BUDGET_MAX_TOKENS = 2**63 - 1
BUDGET_MAX_SETTLE_SECONDS = 30 * 24 * 3600
BUDGET_STATUS_MAX_RESERVATIONS = 50

BudgetCost = Annotated[Decimal, Field(ge=0, le=BUDGET_MAX_COST, decimal_places=8)]
BudgetTokens = Annotated[int, Field(ge=0, le=BUDGET_MAX_TOKENS)]


class BudgetMode(StrEnum):
    """`alert_only`: admit and record alerts. `enforce`: refuse an admission
    whose reservation does not fit (only once approved)."""

    ALERT_ONLY = "alert_only"
    ENFORCE = "enforce"


class BudgetPeriod(StrEnum):
    """Accounting window, UTC calendar: current day, current month, or the
    whole project history."""

    DAY = "day"
    MONTH = "month"
    LIFETIME = "lifetime"


class UnknownCostPolicy(StrEnum):
    """A run whose usage has an unknown measure. `charge_reservation`: it costs
    at least its reservation (conservative). `ignore`: only known measures
    count; the unknown entries stay visible in `unknown_entries`."""

    CHARGE_RESERVATION = "charge_reservation"
    IGNORE = "ignore"


class LateUsagePolicy(StrEnum):
    """A finished run that reported no usage after `settle_after_seconds`.
    `hold_reservation`: its reservation stays charged until usage arrives.
    `release`: nothing is charged until usage arrives. Usage reported later
    always replaces the held amount."""

    HOLD_RESERVATION = "hold_reservation"
    RELEASE = "release"


class BudgetApprovalStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"


class CeilingGuarantee(StrEnum):
    """What the effective policy actually guarantees. `none`: alerts only.
    `admission_only`: admitted reservations stay within the limits; actual
    consumption, reported after the run, may still exceed them."""

    NONE = "none"
    ADMISSION_ONLY = "admission_only"


class BudgetMetric(StrEnum):
    COST = "cost"
    TOKENS = "tokens"
    SLOTS = "slots"


class BudgetRefusalReason(StrEnum):
    """Why an `enforce` policy refused an admission (`409 budget_refused`)."""

    COST_EXHAUSTED = "budget_cost_exhausted"
    TOKENS_EXHAUSTED = "budget_tokens_exhausted"
    SLOTS_EXHAUSTED = "budget_slots_exhausted"


class BudgetAlertCode(StrEnum):
    THRESHOLD_REACHED = "threshold_reached"
    LIMIT_EXCEEDED = "limit_exceeded"
    SLOTS_EXHAUSTED = "slots_exhausted"
    UNKNOWN_USAGE = "unknown_usage"
    ENFORCE_PENDING_APPROVAL = "enforce_pending_approval"


class BudgetReservationStatus(StrEnum):
    """`held`: run admitted, not reconciled. `settled`: run over, charged from
    the ledger (or its reservation, per policy). `released`: nothing held."""

    HELD = "held"
    SETTLED = "settled"
    RELEASED = "released"


class SettleBasis(StrEnum):
    MEASURED = "measured"
    RESERVATION = "reservation"
    NONE = "none"


class BudgetPolicyFields(ContractModel):
    mode: BudgetMode = BudgetMode.ALERT_ONLY
    period: BudgetPeriod = BudgetPeriod.MONTH
    currency: CurrencyCode = "USD"
    cost_limit: BudgetCost | None = None
    token_limit: BudgetTokens | None = None
    max_active_launches: int | None = Field(default=None, ge=1, le=1000)
    reservation_cost: BudgetCost | None = None
    reservation_tokens: BudgetTokens | None = None
    unknown_cost: UnknownCostPolicy = UnknownCostPolicy.CHARGE_RESERVATION
    late_usage: LateUsagePolicy = LateUsagePolicy.HOLD_RESERVATION
    settle_after_seconds: int = Field(default=3600, ge=0, le=BUDGET_MAX_SETTLE_SECONDS)
    alert_thresholds: list[int] = Field(default_factory=lambda: [80, 100], max_length=10)

    @field_validator("alert_thresholds")
    @classmethod
    def _thresholds(cls, thresholds: list[int]) -> list[int]:
        if any(t < 1 or t > 100 for t in thresholds) or len(set(thresholds)) != len(thresholds):
            raise ValueError("alert thresholds are distinct percentages in 1..100")
        return sorted(thresholds)

    @model_validator(mode="after")
    def _enforceable(self) -> Self:
        """An enforced limit needs a positive per-launch reservation, else
        every admission would fit and the limit would promise nothing."""
        if self.mode is not BudgetMode.ENFORCE:
            return self
        if self.cost_limit is None and self.token_limit is None and not self.max_active_launches:
            raise ValueError("enforce mode needs at least one limit")
        if self.cost_limit is not None and not self.reservation_cost:
            raise ValueError("an enforced cost_limit needs a positive reservation_cost")
        if self.token_limit is not None and not self.reservation_tokens:
            raise ValueError("an enforced token_limit needs a positive reservation_tokens")
        return self


class BudgetPolicyUpdate(BudgetPolicyFields):
    """Create (`expected_version` absent) or replace the project's policy.
    A policy in `enforce` mode is stored pending approval."""

    expected_version: int | None = None


class BudgetPolicyApprove(ContractModel):
    expected_version: int


class BudgetPolicy(BudgetPolicyFields, VersionedModel):
    id: UUID
    project_id: UUID
    approval_status: BudgetApprovalStatus
    effective_mode: BudgetMode
    ceiling_guarantee: CeilingGuarantee
    proposed_by_user_id: UUID | None = None
    approved_by_user_id: UUID | None = None
    approved_at: datetime | None = None


class BudgetAlert(ContractModel):
    code: BudgetAlertCode
    metric: BudgetMetric | None = None
    threshold: int | None = None


class BudgetMeter(ContractModel):
    """One limited metric over the current window. `consumed`: charged by
    reconciled runs and usage outside launches. `held`: outstanding
    reservations of runs not reconciled yet. `unknown_entries`: ledger
    entries whose measure for this metric is unknown (or in another currency)."""

    metric: BudgetMetric
    limit: Decimal | None = None
    consumed: Decimal
    held: Decimal
    unknown_entries: int = 0


class BudgetReservation(ContractModel):
    id: UUID
    task_launch_id: UUID
    status: BudgetReservationStatus
    reserved_cost: Decimal | None = None
    reserved_tokens: int | None = None
    settle_basis: SettleBasis | None = None
    alerts: list[BudgetAlert] = Field(default_factory=list)
    created_at: AwareDatetime
    settled_at: AwareDatetime | None = None


class BudgetStatus(ContractModel):
    """Read model of a project's budget. Without a policy: `alert_only`, no
    meter, nothing limited."""

    project_id: UUID
    policy: BudgetPolicy | None = None
    effective_mode: BudgetMode = BudgetMode.ALERT_ONLY
    ceiling_guarantee: CeilingGuarantee = CeilingGuarantee.NONE
    period_start: AwareDatetime | None = None
    meters: list[BudgetMeter] = Field(default_factory=list)
    active_launches: int = 0
    reservations: list[BudgetReservation] = Field(
        default_factory=list, max_length=BUDGET_STATUS_MAX_RESERVATIONS
    )


class BudgetRefusal(ContractModel):
    """`detail` of `409 budget_refused`."""

    error_code: str = "budget_refused"
    reason: BudgetRefusalReason
    metric: BudgetMetric
    limit: Decimal
    consumed: Decimal
    held: Decimal
    requested: Decimal
    period_start: AwareDatetime | None = None
    ceiling_guarantee: CeilingGuarantee = CeilingGuarantee.ADMISSION_ONLY
