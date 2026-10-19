"""Configuration history of a project (P06-history-option, DEC-0221).

The population is TaskLaunch, never a ledger row: every launch of the period
(`created_at` in `[since, until)`) lands in exactly one configuration group or
is missing its configuration. A group pins the harness and profile the launch
was requested with, and derives `harness_version`/`provider`/`model` from the
ledger entries linked by `task_launch_id` — `None` when nobody reported them,
`"mixed"` when entries disagree. Those derived fields are labelled by the
`ledger_derived_fields` caveat: they describe what the ledger *observed*, never
a fact pinned on the launch.

The view is descriptive and never ranked (`ranking` is always `"none"`, groups
are ordered by key, `None` last): the rates it exposes carry their numerator,
denominator, coverage and definition so a reader can always tell a small sample
from a conclusion. Nothing here is a quality judgement.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.task_launch import TERMINAL_STATUSES
from studio_contracts.usage import (
    CONFIGURATION_HISTORY_MAX_GROUPS,
    CONFIGURATION_MIXED,
    LEDGER_DERIVED_CAVEAT,
    NO_MINIMUM_CAVEAT,
    NOT_RANKED_CAVEAT,
    TESTS_NOT_QUALITY_CAVEAT,
    CacheTokenScope,
    ConfigurationHistory,
    ConfigurationHistoryGroup,
    ConfigurationHistoryUnattributed,
    ConfigurationKey,
    ConfigurationRate,
    ConfigurationRateKey,
    MeasurementCoverage,
    UsageCostTotal,
    UsageGroupKey,
    UsageTokenTotal,
)

from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.usage import UsageLedgerEntryModel
from studio_api.services.authz import Principal, ensure_project_access
from studio_api.services.usage import _AggregateAccumulator, _MetricAccumulator

_CONFIGURATION_HISTORY_DEFAULT_DAYS = 30

_MEASURED = MeasurementCoverage.MEASURED.value
_ESTIMATED = MeasurementCoverage.ESTIMATED.value
_UNKNOWN = MeasurementCoverage.UNKNOWN.value
_ADDITIONAL_TO_INPUT = CacheTokenScope.ADDITIONAL_TO_INPUT.value

_TERMINAL_STATUSES = frozenset(item.value for item in TERMINAL_STATUSES)
_SUCCEEDED = "succeeded"

_LEDGER_KEY_FIELDS = ("harness_version", "provider", "model")

_RATE_DEFINITIONS: dict[ConfigurationRateKey, str] = {
    ConfigurationRateKey.SUCCEEDED: "lancements réussis sur lancements terminaux",
    ConfigurationRateKey.SESSION_LINKED: (
        "lancements rattachés à une session sur tous les lancements"
    ),
    ConfigurationRateKey.USAGE_MEASURED: (
        "lancements dont au moins une entrée du registre d'usage a un total de tokens "
        "mesuré ou estimé, sur tous les lancements"
    ),
}

_CAVEATS = [
    TESTS_NOT_QUALITY_CAVEAT,
    NOT_RANKED_CAVEAT,
    NO_MINIMUM_CAVEAT,
    LEDGER_DERIVED_CAVEAT,
]


def _total_tokens(entry: UsageLedgerEntryModel) -> tuple[int | None, bool]:
    """Prompt + completion, plus cached tokens only when they are not already
    inside `tokens_in`; `None` as soon as a needed component is unknown, exactly
    as `UsageMetrics.total_tokens` and `_total_tokens_columns` define it."""
    if entry.tokens_in is None or entry.tokens_out is None:
        return None, False
    total = entry.tokens_in + entry.tokens_out
    estimated = entry.tokens_in_coverage == _ESTIMATED or entry.tokens_out_coverage == _ESTIMATED
    if entry.cached_tokens_scope == _ADDITIONAL_TO_INPUT:
        if entry.tokens_cached is None:
            return None, False
        total += entry.tokens_cached
        estimated = estimated or entry.tokens_cached_coverage == _ESTIMATED
    return total, estimated


def _add_cost(acc: _MetricAccumulator, entry: UsageLedgerEntryModel) -> None:
    coverage = entry.cost_coverage
    acc.add(
        entry.cost,
        1 if coverage == _MEASURED else 0,
        1 if coverage == _ESTIMATED else 0,
        1 if coverage == _UNKNOWN else 0,
    )


def _usage_totals(
    entries: list[UsageLedgerEntryModel],
) -> tuple[UsageTokenTotal, UsageCostTotal]:
    """Total tokens and cost of a set of ledger entries, reusing the summary's
    accumulators so an unknown measure is never folded into a zero."""
    accumulator = _AggregateAccumulator(key=UsageGroupKey())
    for entry in entries:
        total, estimated = _total_tokens(entry)
        accumulator.metrics["total_tokens"].add(
            total,
            1 if total is not None and not estimated else 0,
            1 if total is not None and estimated else 0,
            0 if total is not None else 1,
        )
        _add_cost(accumulator.metrics["cost"], entry)
        if entry.cost_currency is not None:
            accumulator.cost_by_currency.setdefault(
                entry.cost_currency, _MetricAccumulator()
            )
            _add_cost(accumulator.cost_by_currency[entry.cost_currency], entry)
    aggregate = accumulator.finalize()
    return aggregate.total_tokens, aggregate.cost


def _ledger_derived(
    entries: list[UsageLedgerEntryModel], attribute: str
) -> str | None:
    """Distinct value of a ledger-derived field across a launch's linked
    entries: `None` when no entry reported it, `"mixed"` when they disagree."""
    values = {value for entry in entries if (value := getattr(entry, attribute)) is not None}
    if not values:
        return None
    if len(values) == 1:
        return str(next(iter(values)))
    return CONFIGURATION_MIXED


def _key_values(launch: TaskLaunchModel, linked: list[UsageLedgerEntryModel]) -> tuple[object, ...]:
    return (
        launch.harness_id,
        launch.profile_key,
        launch.profile_contract_version,
        launch.profile_digest,
        *(_ledger_derived(linked, attribute) for attribute in _LEDGER_KEY_FIELDS),
    )


def _key(values: tuple[object, ...]) -> ConfigurationKey:
    harness, profile_key, profile_version, profile_digest, harness_version, provider, model = values
    return ConfigurationKey.model_validate(
        {
            "harness": harness,
            "profile_key": profile_key,
            "profile_contract_version": profile_version,
            "profile_digest": profile_digest,
            "harness_version": harness_version,
            "provider": provider,
            "model": model,
        }
    )


def _sort_key(values: tuple[object, ...]) -> tuple[object, ...]:
    """Stable order on the key, `None` last: at a given position the values
    share a type, so only the presence flag has to lead the comparison."""
    return tuple((value is None, value) for value in values)


@dataclass
class _Group:
    key_values: tuple[object, ...]
    launches: list[TaskLaunchModel] = field(default_factory=list)
    ledger: list[UsageLedgerEntryModel] = field(default_factory=list)
    ai_work_entries: int = 0


def _rate(
    key: ConfigurationRateKey,
    numerator: int,
    denominator: int,
    covered: int,
    launches: int,
) -> ConfigurationRate:
    return ConfigurationRate(
        key=key,
        definition=_RATE_DEFINITIONS[key],
        numerator=numerator,
        denominator=denominator,
        covered=covered,
        launches=launches,
        value=(numerator / denominator) if denominator else None,
    )


def _rates(
    launches: list[TaskLaunchModel], usage_measured: int
) -> list[ConfigurationRate]:
    count = len(launches)
    terminal = sum(1 for launch in launches if launch.status in _TERMINAL_STATUSES)
    succeeded = sum(1 for launch in launches if launch.status == _SUCCEEDED)
    session_linked = sum(1 for launch in launches if launch.session_id is not None)
    return [
        _rate(ConfigurationRateKey.SUCCEEDED, succeeded, terminal, terminal, count),
        _rate(ConfigurationRateKey.SESSION_LINKED, session_linked, count, count, count),
        _rate(ConfigurationRateKey.USAGE_MEASURED, usage_measured, count, count, count),
    ]


def _group(group: _Group) -> ConfigurationHistoryGroup:
    launches = group.launches
    linked_by_launch: dict[uuid.UUID, list[UsageLedgerEntryModel]] = {}
    for entry in group.ledger:
        assert entry.task_launch_id is not None
        linked_by_launch.setdefault(entry.task_launch_id, []).append(entry)
    usage_measured = sum(
        1
        for launch in launches
        if any(_total_tokens(entry)[0] is not None for entry in linked_by_launch.get(launch.id, []))
    )
    total_tokens, cost = _usage_totals(group.ledger)
    timestamps = [launch.created_at for launch in launches]
    return ConfigurationHistoryGroup(
        key=_key(group.key_values),
        launches=len(launches),
        first_requested_at=min(timestamps),
        last_requested_at=max(timestamps),
        status_counts=dict(sorted(Counter(launch.status for launch in launches).items())),
        rates=_rates(launches, usage_measured),
        ledger_entries=len(group.ledger),
        ai_work_entries=group.ai_work_entries,
        total_tokens=total_tokens,
        cost=cost,
    )


async def configuration_history(
    session: AsyncSession,
    principal: Principal,
    *,
    project_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    max_groups: int = CONFIGURATION_HISTORY_MAX_GROUPS,
) -> ConfigurationHistory:
    ensure_project_access(principal, project_id)
    if until is None:
        until = datetime.now(UTC)
    if since is None:
        since = until - timedelta(days=_CONFIGURATION_HISTORY_DEFAULT_DAYS)
    if until < since:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"error_code": "invalid_usage_period"}
        )

    launches = list(
        (
            await session.scalars(
                select(TaskLaunchModel).where(
                    TaskLaunchModel.project_id == project_id,
                    TaskLaunchModel.created_at >= since,
                    TaskLaunchModel.created_at < until,
                )
            )
        ).all()
    )
    launch_ids = [launch.id for launch in launches]

    linked_by_launch: dict[uuid.UUID, list[UsageLedgerEntryModel]] = {}
    if launch_ids:
        linked = await session.scalars(
            select(UsageLedgerEntryModel).where(
                UsageLedgerEntryModel.project_id == project_id,
                UsageLedgerEntryModel.task_launch_id.in_(launch_ids),
            )
        )
        for entry in linked:
            assert entry.task_launch_id is not None
            linked_by_launch.setdefault(entry.task_launch_id, []).append(entry)

    groups: dict[tuple[object, ...], _Group] = {}
    for launch in launches:
        values = _key_values(launch, linked_by_launch.get(launch.id, []))
        group = groups.setdefault(values, _Group(key_values=values))
        group.launches.append(launch)
        group.ledger.extend(linked_by_launch.get(launch.id, []))

    launch_sessions = {launch.session_id for launch in launches if launch.session_id is not None}
    if launch_sessions:
        ai_work_clause = or_(
            AIWorkLogModel.session_id.in_(launch_sessions),
            and_(AIWorkLogModel.started_at >= since, AIWorkLogModel.started_at < until),
        )
    else:
        ai_work_clause = and_(
            AIWorkLogModel.started_at >= since, AIWorkLogModel.started_at < until
        )
    ai_works = list(
        (
            await session.scalars(
                select(AIWorkLogModel).where(
                    AIWorkLogModel.project_id == project_id, ai_work_clause
                )
            )
        ).all()
    )

    sessions_by_group = {
        values: {launch.session_id for launch in group.launches if launch.session_id is not None}
        for values, group in groups.items()
    }
    unattributed_ai_work = 0
    for work in ai_works:
        if work.session_id is not None:
            matched = False
            for values, sessions in sessions_by_group.items():
                if work.session_id in sessions:
                    groups[values].ai_work_entries += 1
                    matched = True
            if matched:
                continue
        if work.started_at >= since and work.started_at < until and (
            work.session_id is None or work.session_id not in launch_sessions
        ):
            unattributed_ai_work += 1

    unattributed_ledger = int(
        await session.scalar(
            select(func.count())
            .select_from(UsageLedgerEntryModel)
            .where(
                UsageLedgerEntryModel.project_id == project_id,
                UsageLedgerEntryModel.task_launch_id.is_(None),
                UsageLedgerEntryModel.period_start >= since,
                UsageLedgerEntryModel.period_start < until,
            )
        )
        or 0
    )

    ordered = sorted(groups.values(), key=lambda item: _sort_key(item.key_values))
    return ConfigurationHistory(
        project_id=project_id,
        since=since,
        until=until,
        generated_at=datetime.now(UTC),
        launches=len(launches),
        groups=[_group(item) for item in ordered[:max_groups]],
        unattributed=ConfigurationHistoryUnattributed(
            ledger_entries=unattributed_ledger,
            ai_work_entries=unattributed_ai_work,
        ),
        caveats=list(_CAVEATS),
        truncated=len(ordered) > max_groups,
    )
