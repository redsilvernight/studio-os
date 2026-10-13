"""`UsageLedgerEntry` contract (DEC-0197): what an agent run actually consumed,
with the provenance and the per-metric coverage of every measure.

A ledger entry is a measurement record, never an estimate smuggled in as fact.
Every metric carries its own coverage (`measured`, `estimated` or `unknown`), and
a metric nobody could measure is `None` with coverage `unknown` — never a
fabricated zero, so a consumer can always tell "nothing happened" from "nobody
measured". Cached tokens are a separate metric carrying an explicit scope, so a
cache count the collector already folded into `tokens_in` is never counted twice.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from studio_contracts.bootstrap import HarnessId
from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel

USAGE_SOURCE_EVENT_ID_MAX = 128
USAGE_TAG_MAX = 64
USAGE_MODEL_MAX = 128

SourceEventId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=USAGE_SOURCE_EVENT_ID_MAX,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
"""Stable identifier of the collector-side fact this entry records. Bounded to a
token charset so no path, argument or free text is representable."""

CollectorId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=USAGE_TAG_MAX, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
]
UsageTag = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=USAGE_TAG_MAX, pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_-]*$"
    ),
]
"""Open provenance string (collector version, price list id, provider): bounded
and charset-limited, never whitelisted, never an authorization input."""

ModelId = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=USAGE_MODEL_MAX, pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_:@/\[\]-]*$"
    ),
]
"""Provider model identifier as the runtime reports it (`vendor/model`,
`model@date`, `model[1m]`): same bounded-tag rule, with the separators real
model ids use."""

CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]

NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


class MeasurementCoverage(StrEnum):
    """What a measure is worth. `measured`: read from the runtime itself.
    `estimated`: derived by the collector from another signal, usable but never
    presented as a fact. `unknown`: nobody could measure it — the value is
    `None`, and no consumer may read that as zero."""

    MEASURED = "measured"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class MeasurementUnit(StrEnum):
    TOKENS = "tokens"
    SECONDS = "seconds"
    CURRENCY = "currency"


class Measurement[V: (int, Decimal)](ContractModel):
    """One quantity and the coverage that says what it is worth.

    `value` is `None` exactly when the coverage is `unknown`, and is always
    present otherwise: an absent measure and a measured zero are never the same
    payload. Non-negative: a negative token count or duration is a collector
    bug, not a measurement."""

    value: V | None = None
    coverage: MeasurementCoverage = MeasurementCoverage.UNKNOWN

    @model_validator(mode="after")
    def _coverage_matches_value(self) -> Self:
        if self.coverage is MeasurementCoverage.UNKNOWN:
            if self.value is not None:
                raise ValueError("an unknown measurement carries no value")
        elif self.value is None:
            raise ValueError(f"a {self.coverage} measurement carries a value")
        return self


class TokenMeasurement(Measurement[NonNegativeInt]):
    """Token count. The unit is fixed by the field it lives in, so a token
    metric can never be filled with a duration."""

    unit: Literal[MeasurementUnit.TOKENS] = MeasurementUnit.TOKENS


class DurationMeasurement(Measurement[NonNegativeDecimal]):
    """Wall-clock duration of the covered period, in seconds."""

    unit: Literal[MeasurementUnit.SECONDS] = MeasurementUnit.SECONDS


class CostMeasurement(Measurement[NonNegativeDecimal]):
    """Monetary cost. The currency travels with the value: a cost without a
    currency is not a cost. Absent cost is `unknown`, never `0` — a free run
    and an unpriced one are not the same fact."""

    unit: Literal[MeasurementUnit.CURRENCY] = MeasurementUnit.CURRENCY
    currency: CurrencyCode | None = None

    @model_validator(mode="after")
    def _value_needs_a_currency(self) -> Self:
        if self.value is not None and self.currency is None:
            raise ValueError("a cost carries its currency")
        if self.currency is not None and self.value is None:
            raise ValueError("a currency without a value is not a cost")
        return self


class CacheTokenScope(StrEnum):
    """Where the cached token count sits relative to `tokens_in`, so a reader
    never adds a cache count twice. `included_in_input`: the collector already
    counts cache hits inside `tokens_in` (the total is in + out).
    `additional_to_input`: the cached count is disjoint from `tokens_in` —
    cache reads and cache writes billed apart from the prompt — so the total is
    in + out + cached."""

    INCLUDED_IN_INPUT = "included_in_input"
    ADDITIONAL_TO_INPUT = "additional_to_input"


class UsageProvenance(ContractModel):
    """Who produced the measure. `collector`/`collector_version` name the tool
    that emitted the entry, `harness`/`harness_version` the agent runtime it ran:
    two entries with identical numbers but different provenance are not the same
    measurement, and a re-run of a different harness version is a new entry
    rather than an overwrite."""

    collector: CollectorId
    collector_version: UsageTag | None = None
    harness: HarnessId | None = None
    harness_version: UsageTag | None = None
    provider: UsageTag | None = None
    model: ModelId | None = None


class PricingRef(ContractModel):
    """The dated price list a cost was computed from, for the model named in the
    provenance. Required for an `estimated` cost (tokens times a price): without
    it the cost cannot be re-derived once prices move, and two entries priced on
    different dates are not comparable. Optional for a `measured` cost (the
    amount actually billed), forbidden for an `unknown` one."""

    price_list_id: UsageTag
    effective_from: AwareDatetime


class UsageMetrics(ContractModel):
    """The measures of one ledger entry. Each one is independently absent:
    a collector that reports prompt tokens but no duration leaves `duration`
    `unknown` instead of inventing `0`."""

    tokens_in: TokenMeasurement = Field(default_factory=TokenMeasurement)
    tokens_out: TokenMeasurement = Field(default_factory=TokenMeasurement)
    tokens_cached: TokenMeasurement = Field(default_factory=TokenMeasurement)
    cached_tokens_scope: CacheTokenScope = CacheTokenScope.INCLUDED_IN_INPUT
    cost: CostMeasurement = Field(default_factory=CostMeasurement)
    duration: DurationMeasurement = Field(default_factory=DurationMeasurement)

    @model_validator(mode="after")
    def _cache_not_larger_than_input(self) -> Self:
        if (
            self.cached_tokens_scope is CacheTokenScope.INCLUDED_IN_INPUT
            and self.tokens_in.value is not None
            and self.tokens_cached.value is not None
            and self.tokens_cached.value > self.tokens_in.value
        ):
            raise ValueError("cached tokens included in tokens_in cannot exceed tokens_in")
        return self

    @property
    def coverage_by_metric(self) -> dict[str, MeasurementCoverage]:
        return {
            "tokens_in": self.tokens_in.coverage,
            "tokens_out": self.tokens_out.coverage,
            "tokens_cached": self.tokens_cached.coverage,
            "cost": self.cost.coverage,
            "duration": self.duration.coverage,
        }

    @property
    def total_tokens(self) -> int | None:
        """Prompt + completion, plus the cached tokens only when they are not
        already inside `tokens_in` (never a double count). `None` as soon as a
        needed component is `unknown`: a partial sum would be a fabricated total."""

        if self.tokens_in.value is None or self.tokens_out.value is None:
            return None
        total = self.tokens_in.value + self.tokens_out.value
        if self.cached_tokens_scope is CacheTokenScope.ADDITIONAL_TO_INPUT:
            if self.tokens_cached.value is None:
                return None
            total += self.tokens_cached.value
        return total


def _check_period_and_cost(
    period_start: AwareDatetime,
    period_end: AwareDatetime,
    cost: CostMeasurement,
    pricing: PricingRef | None,
) -> None:
    if period_end < period_start:
        raise ValueError("period_end precedes period_start")
    if cost.coverage is MeasurementCoverage.UNKNOWN:
        if pricing is not None:
            raise ValueError("a price list without a cost is not a pricing reference")
    elif cost.coverage is MeasurementCoverage.ESTIMATED and pricing is None:
        raise ValueError("an estimated cost carries the dated price list it was computed from")


class UsageEntryFields(UsageMetrics):
    """Identity and provenance shared by the ingestion payload and the stored
    entry."""

    project_id: UUID
    machine_id: UUID
    source_event_id: SourceEventId
    provenance: UsageProvenance
    period_start: AwareDatetime
    period_end: AwareDatetime
    task_id: UUID | None = None
    session_id: UUID | None = None
    task_launch_id: UUID | None = None
    ai_work_id: UUID | None = None
    pricing: PricingRef | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        _check_period_and_cost(self.period_start, self.period_end, self.cost, self.pricing)
        return self


class UsageLedgerEntryCreate(UsageEntryFields, IdempotentCreate):
    """Ingestion payload. Ingestion is deduplicated on `(machine_id,
    source_event_id)`: a replayed or delayed collector event returns the entry
    already recorded instead of appending a second row. A late correction of an
    already recorded fact targets that entry with `UsageLedgerCorrection`, never
    a fresh `source_event_id`."""


class UsageLedgerEntry(UsageEntryFields, VersionedModel):
    """Stored ledger entry. `version` grows by one on each accepted correction;
    a correction carries `expected_version`, so a correction that raced another
    one is refused rather than silently overwriting it."""

    id: UUID


class UsageLedgerCorrection(UsageMetrics, IdempotentCreate):
    """A late or corrected measure for a fact already ingested, keyed by the same
    `(machine_id, source_event_id)`. The measured block is replaced as a whole —
    a partial merge would silently keep a stale number beside a fresh one — and
    the identity of the entry (project, links, collector) is fixed and carries
    no field here: a correction cannot move an entry to another project,
    machine, session or work entry, and a different `collector` is refused."""

    machine_id: UUID
    source_event_id: SourceEventId
    expected_version: int = Field(ge=1)
    provenance: UsageProvenance
    period_start: AwareDatetime
    period_end: AwareDatetime
    pricing: PricingRef | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        _check_period_and_cost(self.period_start, self.period_end, self.cost, self.pricing)
        return self


USAGE_SUMMARY_MAX_GROUPS = 100


class UsageGroupBy(StrEnum):
    """Dimension of a usage summary. `configuration` is the provenance the
    runtime reported (harness, provider, model); `day` is the UTC day of
    `period_start`."""

    NONE = "none"
    TASK = "task"
    CONFIGURATION = "configuration"
    DAY = "day"


class UsageTotalStatus(StrEnum):
    """What an aggregated metric is worth, so no client presents a partial or
    incomparable sum as an exact total.

    `none`: no entry in scope. `exact`: every entry measured. `estimated`:
    every entry has a value, at least one estimated. `partial`: some entries
    are `unknown`, `known_sum` is only a lower bound. `unknown`: entries exist
    but none has a value. `mixed_currency` (cost only): known costs are in
    several currencies, they are never added together."""

    NONE = "none"
    EXACT = "exact"
    ESTIMATED = "estimated"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    MIXED_CURRENCY = "mixed_currency"


class UsageCoverageCounts(ContractModel):
    measured_entries: NonNegativeInt = 0
    estimated_entries: NonNegativeInt = 0
    unknown_entries: NonNegativeInt = 0


class UsageTokenTotal(UsageCoverageCounts):
    """Sum of the known values. `known_sum` is a total only when `status` is
    `exact` or `estimated`; it is a lower bound when `partial` and `None` when
    nothing is known."""

    status: UsageTotalStatus
    known_sum: NonNegativeInt | None = None


class UsageDurationTotal(UsageCoverageCounts):
    """Sum of measured wall-clock durations in seconds, same rule as tokens."""

    status: UsageTotalStatus
    known_sum: NonNegativeDecimal | None = None


class UsageCurrencyAmount(ContractModel):
    currency: CurrencyCode
    known_sum: NonNegativeDecimal
    entries: NonNegativeInt


class UsageCostTotal(UsageCoverageCounts):
    """Cost summed per currency. `known_sum`/`currency` are set only when every
    known cost shares one currency; with several currencies `status` is
    `mixed_currency`, `known_sum` is `None` and `by_currency` lists each sum
    apart. An unknown cost is never counted as zero."""

    status: UsageTotalStatus
    known_sum: NonNegativeDecimal | None = None
    currency: CurrencyCode | None = None
    by_currency: list[UsageCurrencyAmount] = Field(default_factory=list)


class UsageSourceCount(ContractModel):
    """Collector that produced entries of the aggregate, with its entry count."""

    collector: CollectorId
    entries: NonNegativeInt


class UsageGroupKey(ContractModel):
    """Value of the grouping dimension. Fields outside the requested dimension
    stay `None`; a `None` inside it means the entries did not carry it (entry
    without task, model not reported)."""

    task_id: UUID | None = None
    task_title: str | None = None
    harness: str | None = None
    provider: str | None = None
    model: str | None = None
    day: date | None = None


class UsageAggregate(ContractModel):
    """Aggregated measures of a set of ledger entries. Each entry counts once,
    in its latest corrected form: replays and cumulative snapshots never add
    up (ingestion is deduplicated on `(machine_id, source_event_id)`)."""

    key: UsageGroupKey = Field(default_factory=UsageGroupKey)
    entries: NonNegativeInt
    first_period_start: AwareDatetime | None = None
    last_period_end: AwareDatetime | None = None
    tokens_in: UsageTokenTotal
    tokens_out: UsageTokenTotal
    tokens_cached: UsageTokenTotal
    total_tokens: UsageTokenTotal
    cost: UsageCostTotal
    duration: UsageDurationTotal
    sources: list[UsageSourceCount] = Field(default_factory=list)


class UsageSummary(ContractModel):
    """Usage of a project (optionally one task) over a period of `period_start`.
    `total` covers every entry in scope, including groups cut by
    `USAGE_SUMMARY_MAX_GROUPS` (`truncated`). Clients display these values as
    returned and never re-add groups into a total."""

    project_id: UUID
    task_id: UUID | None = None
    group_by: UsageGroupBy
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None
    generated_at: AwareDatetime
    total: UsageAggregate
    groups: list[UsageAggregate] = Field(default_factory=list)
    truncated: bool = False
