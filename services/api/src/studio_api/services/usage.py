from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.usage import (
    UsageEntryFields,
    UsageLedgerCorrection,
    UsageLedgerEntry,
    UsageLedgerEntryCreate,
    UsageMetrics,
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
            or agent.machine_id != entry.machine_id
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
