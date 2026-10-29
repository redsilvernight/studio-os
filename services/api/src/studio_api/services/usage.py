from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.usage import (
    USAGE_SUMMARY_MAX_GROUPS,
    CacheTokenScope,
    MeasurementCoverage,
    UsageAggregate,
    UsageCostTotal,
    UsageCurrencyAmount,
    UsageDurationTotal,
    UsageEntryFields,
    UsageGroupBy,
    UsageGroupKey,
    UsageLedgerCorrection,
    UsageLedgerEntry,
    UsageLedgerEntryCreate,
    UsageMetrics,
    UsageSourceCount,
    UsageSummary,
    UsageTokenTotal,
    UsageTotalStatus,
)

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.usage import UsageLedgerEntryModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_project_access,
    forbidden,
    get_launch_scope,
    owns_agent,
    project_visibility_clause,
)


def _conflict(code: str, **details: Any) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"error_code": code, **details})


def _ensure_own_machine(principal: Principal, machine_id: uuid.UUID) -> None:
    ensure_can_write(principal, "usage")
    if machine_id != principal.machine.id:
        raise _conflict("actor_not_owned")


def _ensure_launch_scope(principal: Principal, entry: UsageEntryFields) -> None:
    scope = get_launch_scope(principal.machine)
    if scope is not None and (
        entry.project_id != scope.project_id
        or entry.task_id != scope.task_id
        or entry.task_launch_id != scope.launch_id
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail={"error_code": "launch_credential_scope"}
        )


def validate_measurements(entry: UsageMetrics) -> None:
    for name, maximum in (
        ("tokens_in", 2**63 - 1),
        ("tokens_out", 2**63 - 1),
        ("tokens_cached", 2**63 - 1),
        ("cost", Decimal("9999999999.99999999")),
        ("duration", Decimal("99999999999.999")),
    ):
        value = getattr(entry, name).value
        if value is not None and value > maximum:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "invalid_usage_measurement", "metric": name},
            )


async def validate_identity(
    session: AsyncSession, principal: Principal, entry: UsageEntryFields
) -> None:
    _ensure_launch_scope(principal, entry)
    ensure_project_access(principal, entry.project_id, "write")
    _ensure_own_machine(principal, entry.machine_id)
    validate_measurements(entry)
    if await session.get(ProjectModel, entry.project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")

    task_ids: set[uuid.UUID] = set()
    session_ids: set[uuid.UUID] = set()
    if entry.task_id is not None:
        task_ids.add(entry.task_id)
    if entry.session_id is not None:
        session_ids.add(entry.session_id)
    if entry.task_launch_id is not None:
        launch = await session.get(TaskLaunchModel, entry.task_launch_id)
        if launch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "task launch not found")
        if launch.machine_id != entry.machine_id:
            raise forbidden("task_launch", "link")
        if launch.project_id != entry.project_id:
            raise _conflict("invalid_usage_link", resource="task_launch")
        task_ids.add(launch.task_id)
        if launch.session_id is not None:
            session_ids.add(launch.session_id)
    if entry.ai_work_id is not None:
        work = await session.get(AIWorkLogModel, entry.ai_work_id)
        if work is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ai_work entry not found")
        agent = await session.get(AgentModel, work.agent_id)
        if (
            work.machine_id not in (None, entry.machine_id)
            or agent is None
            or not owns_agent(agent, principal.machine)
        ):
            raise forbidden("ai_work", "link")
        if work.project_id != entry.project_id:
            raise _conflict("invalid_usage_link", resource="ai_work")
        if work.task_id is not None:
            task_ids.add(work.task_id)
        if work.session_id is not None:
            session_ids.add(work.session_id)
    for session_id in session_ids:
        linked = await session.get(WorkSessionModel, session_id)
        if linked is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        if linked.machine_id != entry.machine_id:
            raise forbidden("session", "link")
        task_ids.add(linked.task_id)
    if len(task_ids) > 1 or len(session_ids) > 1:
        raise _conflict("invalid_usage_link")
    for task_id in task_ids:
        task = await session.get(TaskModel, task_id)
        if task is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
        if task.project_id != entry.project_id:
            raise _conflict("invalid_usage_link", resource="task")


def to_entry(row: UsageLedgerEntryModel) -> UsageLedgerEntry:
    return UsageLedgerEntry.model_validate(
        dict(
            id=row.id,
            project_id=row.project_id,
            machine_id=row.machine_id,
            source_event_id=row.source_event_id,
            task_id=row.task_id,
            session_id=row.session_id,
            task_launch_id=row.task_launch_id,
            ai_work_id=row.ai_work_id,
            provenance={
                "collector": row.collector,
                "collector_version": row.collector_version,
                "harness": row.harness,
                "harness_version": row.harness_version,
                "provider": row.provider,
                "model": row.model,
            },
            period_start=row.period_start,
            period_end=row.period_end,
            tokens_in={"value": row.tokens_in, "coverage": row.tokens_in_coverage},
            tokens_out={"value": row.tokens_out, "coverage": row.tokens_out_coverage},
            tokens_cached={"value": row.tokens_cached, "coverage": row.tokens_cached_coverage},
            cached_tokens_scope=row.cached_tokens_scope,
            cost={"value": row.cost, "coverage": row.cost_coverage, "currency": row.cost_currency},
            duration={"value": row.duration_seconds, "coverage": row.duration_coverage},
            pricing={"price_list_id": row.price_list_id, "effective_from": row.price_effective_from}
            if row.price_list_id is not None
            else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
            version=row.version,
        )
    )


def _measurement_values(entry: UsageLedgerEntryCreate | UsageLedgerCorrection) -> dict[str, Any]:
    values: dict[str, Any] = entry.provenance.model_dump(mode="json")
    values.update(
        period_start=entry.period_start,
        period_end=entry.period_end,
        cached_tokens_scope=entry.cached_tokens_scope.value,
        cost=entry.cost.value,
        cost_coverage=entry.cost.coverage.value,
        cost_currency=entry.cost.currency,
        duration_seconds=entry.duration.value,
        duration_coverage=entry.duration.coverage.value,
        price_list_id=entry.pricing.price_list_id if entry.pricing is not None else None,
        price_effective_from=entry.pricing.effective_from if entry.pricing is not None else None,
    )
    for name in ("tokens_in", "tokens_out", "tokens_cached"):
        metric = getattr(entry, name)
        values[name] = metric.value
        values[f"{name}_coverage"] = metric.coverage.value
    return values


async def _get_source(
    session: AsyncSession, machine_id: uuid.UUID, source_event_id: str, *, lock: bool = False
) -> UsageLedgerEntryModel | None:
    stmt = select(UsageLedgerEntryModel).where(
        UsageLedgerEntryModel.machine_id == machine_id,
        UsageLedgerEntryModel.source_event_id == source_event_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt.execution_options(populate_existing=True))
    return result.scalar_one_or_none()


async def create_usage(
    session: AsyncSession,
    principal: Principal,
    entry: UsageLedgerEntryCreate,
    *,
    commit: bool = True,
) -> UsageLedgerEntryModel:
    await validate_identity(session, principal, entry)
    identity = {
        name: getattr(entry, name)
        for name in (
            "project_id",
            "machine_id",
            "source_event_id",
            "task_id",
            "session_id",
            "task_launch_id",
            "ai_work_id",
        )
    }
    await session.execute(
        pg_insert(UsageLedgerEntryModel)
        .values(**identity, **_measurement_values(entry))
        .on_conflict_do_nothing(constraint="uq_usage_ledger_machine_source")
    )
    row = await _get_source(session, entry.machine_id, entry.source_event_id)
    assert row is not None
    if any(getattr(row, name) != value for name, value in identity.items()) or (
        row.collector != entry.provenance.collector
    ):
        raise _conflict("usage_identity_conflict")
    await validate_identity(session, principal, to_entry(row))
    await session.flush()
    await session.refresh(row)
    if commit:
        await session.commit()
    return row


async def authorize_correction(
    session: AsyncSession, principal: Principal, correction: UsageLedgerCorrection
) -> UsageLedgerEntryModel:
    _ensure_own_machine(principal, correction.machine_id)
    validate_measurements(correction)
    row = await _get_source(session, correction.machine_id, correction.source_event_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "usage entry not found")
    await validate_identity(session, principal, to_entry(row))
    if row.collector != correction.provenance.collector:
        raise _conflict("usage_identity_conflict")
    return row


async def correct_usage(
    session: AsyncSession,
    principal: Principal,
    correction: UsageLedgerCorrection,
    *,
    commit: bool = True,
) -> UsageLedgerEntryModel:
    _ensure_own_machine(principal, correction.machine_id)
    validate_measurements(correction)
    row = await _get_source(session, correction.machine_id, correction.source_event_id, lock=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "usage entry not found")
    await validate_identity(session, principal, to_entry(row))
    if row.collector != correction.provenance.collector:
        raise _conflict("usage_identity_conflict")
    if row.version != correction.expected_version:
        raise _conflict("version_conflict", server_version=row.version)
    for name, value in _measurement_values(correction).items():
        setattr(row, name, value)
    row.version += 1
    await session.flush()
    await session.refresh(row)
    if commit:
        await session.commit()
    return row


async def list_usage(
    session: AsyncSession,
    principal: Principal,
    *,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    task_launch_id: uuid.UUID | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[UsageLedgerEntryModel]:
    stmt = select(UsageLedgerEntryModel)
    if project_id is not None:
        ensure_project_access(principal, project_id)
        stmt = stmt.where(UsageLedgerEntryModel.project_id == project_id)
    if (
        visible := project_visibility_clause(principal, UsageLedgerEntryModel.project_id)
    ) is not None:
        stmt = stmt.where(visible)
    for value, model, column in (
        (task_id, TaskModel, UsageLedgerEntryModel.task_id),
        (session_id, WorkSessionModel, UsageLedgerEntryModel.session_id),
        (task_launch_id, TaskLaunchModel, UsageLedgerEntryModel.task_launch_id),
    ):
        if value is None:
            continue
        linked = await session.get(model, value)
        if linked is not None:
            if isinstance(linked, WorkSessionModel):
                task = await session.get(TaskModel, linked.task_id)
                if task is not None:
                    ensure_project_access(principal, task.project_id)
            elif isinstance(linked, TaskModel | TaskLaunchModel):
                ensure_project_access(principal, linked.project_id)
        stmt = stmt.where(column == value)
    if since is not None:
        stmt = stmt.where(UsageLedgerEntryModel.updated_at >= since)
    stmt = stmt.order_by(UsageLedgerEntryModel.updated_at, UsageLedgerEntryModel.id).limit(
        max(1, min(limit, 500))
    )
    return list((await session.scalars(stmt)).all())


_MEASURED = MeasurementCoverage.MEASURED.value
_ESTIMATED = MeasurementCoverage.ESTIMATED.value
_UNKNOWN = MeasurementCoverage.UNKNOWN.value


@dataclass
class _MetricAccumulator:
    known_sum: Decimal = Decimal(0)
    measured: int = 0
    estimated: int = 0
    unknown: int = 0

    def add(self, known_sum: Any, measured: int, estimated: int, unknown: int) -> None:
        if known_sum is not None:
            self.known_sum += Decimal(known_sum)
        self.measured += measured
        self.estimated += estimated
        self.unknown += unknown

    def merge(self, other: _MetricAccumulator) -> None:
        self.add(other.known_sum, other.measured, other.estimated, other.unknown)

    @property
    def known(self) -> int:
        return self.measured + self.estimated

    def status(self) -> UsageTotalStatus:
        if self.known == 0:
            return UsageTotalStatus.UNKNOWN if self.unknown else UsageTotalStatus.NONE
        if self.unknown:
            return UsageTotalStatus.PARTIAL
        if self.estimated:
            return UsageTotalStatus.ESTIMATED
        return UsageTotalStatus.EXACT

    def counts(self) -> dict[str, int]:
        return {
            "measured_entries": self.measured,
            "estimated_entries": self.estimated,
            "unknown_entries": self.unknown,
        }

    def tokens(self) -> UsageTokenTotal:
        return UsageTokenTotal(
            status=self.status(),
            known_sum=int(self.known_sum) if self.known else None,
            **self.counts(),
        )

    def duration(self) -> UsageDurationTotal:
        return UsageDurationTotal(
            status=self.status(),
            known_sum=self.known_sum if self.known else None,
            **self.counts(),
        )


_TOKEN_METRICS = ("tokens_in", "tokens_out", "tokens_cached", "total_tokens")
_METRICS = (*_TOKEN_METRICS, "cost", "duration")


def _new_metrics() -> dict[str, _MetricAccumulator]:
    return {name: _MetricAccumulator() for name in _METRICS}


@dataclass
class _AggregateAccumulator:
    key: UsageGroupKey
    entries: int = 0
    first_period_start: datetime | None = None
    last_period_end: datetime | None = None
    metrics: dict[str, _MetricAccumulator] = field(default_factory=_new_metrics)
    cost_by_currency: dict[str, _MetricAccumulator] = field(default_factory=dict)
    sources: dict[str, int] = field(default_factory=dict)

    def span(self, start: datetime | None, end: datetime | None) -> None:
        if start is not None and (
            self.first_period_start is None or start < self.first_period_start
        ):
            self.first_period_start = start
        if end is not None and (self.last_period_end is None or end > self.last_period_end):
            self.last_period_end = end

    def merge(self, other: _AggregateAccumulator) -> None:
        self.entries += other.entries
        self.span(other.first_period_start, other.last_period_end)
        for name, metric in other.metrics.items():
            self.metrics[name].merge(metric)
        for currency, metric in other.cost_by_currency.items():
            self.cost_by_currency.setdefault(currency, _MetricAccumulator()).merge(metric)
        for collector, count in other.sources.items():
            self.sources[collector] = self.sources.get(collector, 0) + count

    def cost(self) -> UsageCostTotal:
        metric = self.metrics["cost"]
        by_currency = [
            UsageCurrencyAmount(currency=currency, known_sum=amount.known_sum, entries=amount.known)
            for currency, amount in sorted(self.cost_by_currency.items())
        ]
        if len(by_currency) > 1:
            return UsageCostTotal(
                status=UsageTotalStatus.MIXED_CURRENCY,
                known_sum=None,
                currency=None,
                by_currency=by_currency,
                **metric.counts(),
            )
        single = by_currency[0] if by_currency else None
        return UsageCostTotal(
            status=metric.status(),
            known_sum=single.known_sum if single is not None else None,
            currency=single.currency if single is not None else None,
            by_currency=by_currency,
            **metric.counts(),
        )

    def finalize(self) -> UsageAggregate:
        return UsageAggregate(
            key=self.key,
            entries=self.entries,
            first_period_start=self.first_period_start,
            last_period_end=self.last_period_end,
            tokens_in=self.metrics["tokens_in"].tokens(),
            tokens_out=self.metrics["tokens_out"].tokens(),
            tokens_cached=self.metrics["tokens_cached"].tokens(),
            total_tokens=self.metrics["total_tokens"].tokens(),
            cost=self.cost(),
            duration=self.metrics["duration"].duration(),
            sources=[
                UsageSourceCount(collector=collector, entries=count)
                for collector, count in sorted(self.sources.items())
            ],
        )


def _coverage_counts(coverage: Any) -> list[Any]:
    return [
        func.count().filter(coverage == _MEASURED),
        func.count().filter(coverage == _ESTIMATED),
        func.count().filter(coverage == _UNKNOWN),
    ]


def _total_tokens_columns() -> tuple[Any, Any]:
    entry = UsageLedgerEntryModel
    additional = entry.cached_tokens_scope == CacheTokenScope.ADDITIONAL_TO_INPUT.value
    total = case(
        (entry.tokens_in.is_(None) | entry.tokens_out.is_(None), None),
        (additional, entry.tokens_in + entry.tokens_out + entry.tokens_cached),
        else_=entry.tokens_in + entry.tokens_out,
    )
    estimated = (
        (entry.tokens_in_coverage == _ESTIMATED)
        | (entry.tokens_out_coverage == _ESTIMATED)
        | (additional & (entry.tokens_cached_coverage == _ESTIMATED))
    )
    return total, estimated


def _group_columns(group_by: UsageGroupBy) -> dict[str, Any]:
    entry = UsageLedgerEntryModel
    if group_by is UsageGroupBy.TASK:
        return {"task_id": entry.task_id, "task_title": TaskModel.title}
    if group_by is UsageGroupBy.CONFIGURATION:
        return {"harness": entry.harness, "provider": entry.provider, "model": entry.model}
    if group_by is UsageGroupBy.DAY:
        return {"day": func.date(func.timezone("UTC", entry.period_start))}
    return {}


def _summary_measures() -> list[Any]:
    entry = UsageLedgerEntryModel
    total_tokens, total_estimated = _total_tokens_columns()
    measures: list[Any] = []
    for name in ("tokens_in", "tokens_out", "tokens_cached"):
        measures.append(func.sum(getattr(entry, name)))
        measures.extend(_coverage_counts(getattr(entry, f"{name}_coverage")))
    measures.extend(
        [
            func.sum(total_tokens),
            func.count().filter(total_tokens.is_not(None) & ~total_estimated),
            func.count().filter(total_tokens.is_not(None) & total_estimated),
            func.count().filter(total_tokens.is_(None)),
            func.sum(entry.cost),
            *_coverage_counts(entry.cost_coverage),
            func.sum(entry.duration_seconds),
            *_coverage_counts(entry.duration_coverage),
        ]
    )
    return measures


def _group_order(item: _AggregateAccumulator) -> tuple[date, datetime]:
    return (
        item.key.day or date.min,
        item.last_period_end or datetime.min.replace(tzinfo=UTC),
    )


async def summarize_usage(
    session: AsyncSession,
    principal: Principal,
    *,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    task_launch_id: uuid.UUID | None = None,
    group_by: UsageGroupBy = UsageGroupBy.NONE,
    since: datetime | None = None,
    until: datetime | None = None,
    max_groups: int = USAGE_SUMMARY_MAX_GROUPS,
) -> UsageSummary:
    ensure_project_access(principal, project_id)
    if since is not None and until is not None and until < since:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"error_code": "invalid_usage_period"}
        )
    entry = UsageLedgerEntryModel
    groups = _group_columns(group_by)
    dimensions = [*groups.values(), entry.cost_currency, entry.collector]
    stmt = select(
        *dimensions,
        func.count(),
        func.min(entry.period_start),
        func.max(entry.period_end),
        *_summary_measures(),
    ).where(entry.project_id == project_id)
    if group_by is UsageGroupBy.TASK:
        stmt = stmt.outerjoin(TaskModel, TaskModel.id == entry.task_id)
    if task_id is not None:
        stmt = stmt.where(entry.task_id == task_id)
    if task_launch_id is not None:
        stmt = stmt.where(entry.task_launch_id == task_launch_id)
    if since is not None:
        stmt = stmt.where(entry.period_start >= since)
    if until is not None:
        stmt = stmt.where(entry.period_start < until)
    stmt = stmt.group_by(*dimensions)

    by_key: dict[tuple[Any, ...], _AggregateAccumulator] = {}
    for row in (await session.execute(stmt)).all():
        key_values = tuple(row[: len(groups)])
        currency, collector, count, first_start, last_end, *values = row[len(groups) :]
        key = UsageGroupKey(**dict(zip(groups, key_values, strict=True)))
        part = _AggregateAccumulator(key=key, entries=count)
        part.span(first_start, last_end)
        for index, name in enumerate(_METRICS):
            part.metrics[name].add(*values[index * 4 : index * 4 + 4])
        if currency is not None:
            part.cost_by_currency[currency] = _MetricAccumulator()
            part.cost_by_currency[currency].merge(part.metrics["cost"])
        part.sources[collector] = count
        by_key.setdefault(key_values, _AggregateAccumulator(key=key)).merge(part)

    total = _AggregateAccumulator(key=UsageGroupKey())
    for aggregate in by_key.values():
        total.merge(aggregate)
    grouped = group_by is not UsageGroupBy.NONE
    ordered = sorted(by_key.values(), key=_group_order, reverse=True) if grouped else []
    return UsageSummary(
        project_id=project_id,
        task_id=task_id,
        task_launch_id=task_launch_id,
        group_by=group_by,
        since=since,
        until=until,
        generated_at=datetime.now(UTC),
        total=total.finalize(),
        groups=[item.finalize() for item in ordered[:max_groups]],
        truncated=len(ordered) > max_groups,
    )
