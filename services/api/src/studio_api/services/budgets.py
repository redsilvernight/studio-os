"""Budget policy and TaskLaunch admission (Mission Control P03-budgets).

Admission runs inside the launch creation transaction, after the project's
policy row is locked `FOR UPDATE`: concurrent admissions of one project are
serialized, each one sees the reservations the previous ones committed, and
`uq_budget_reservations_launch` forbids two reservations for one launch.

Accounting is recomputed from the ledger at read time, never from stored
totals, so usage reported late (or corrected) always replaces what a
reservation held.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.budgets import (
    BUDGET_STATUS_MAX_RESERVATIONS,
    BudgetAlert,
    BudgetAlertCode,
    BudgetApprovalStatus,
    BudgetMeter,
    BudgetMetric,
    BudgetMode,
    BudgetPeriod,
    BudgetPolicy,
    BudgetPolicyApprove,
    BudgetPolicyUpdate,
    BudgetRefusal,
    BudgetRefusalReason,
    BudgetReservation,
    BudgetReservationStatus,
    BudgetStatus,
    CeilingGuarantee,
    LateUsagePolicy,
    SettleBasis,
    UnknownCostPolicy,
)
from studio_contracts.task_launch import TERMINAL_STATUSES, TaskLaunchReasonCode, TaskLaunchStatus

from studio_api.db.models.budget import BudgetPolicyModel, BudgetReservationModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.usage import UsageLedgerEntryModel
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_project_access,
    forbidden,
    get_launch_scope,
)

_TERMINAL = tuple(s.value for s in TERMINAL_STATUSES)
_NEVER_PULLED = (TaskLaunchStatus.REJECTED.value, TaskLaunchStatus.REQUESTED.value)
_UNKNOWN = "unknown"
_HELD = BudgetReservationStatus.HELD.value
_ZERO = Decimal(0)


def _conflict(code: str, **details: Any) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"error_code": code, **details})


def effective_mode(policy: BudgetPolicyModel | None) -> BudgetMode:
    if policy is None or policy.mode != BudgetMode.ENFORCE.value or policy.approved_at is None:
        return BudgetMode.ALERT_ONLY
    return BudgetMode.ENFORCE


def _guarantee(mode: BudgetMode) -> CeilingGuarantee:
    return CeilingGuarantee.ADMISSION_ONLY if mode is BudgetMode.ENFORCE else CeilingGuarantee.NONE


def period_start(period: str, now: datetime) -> datetime | None:
    if period == BudgetPeriod.DAY.value:
        return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == BudgetPeriod.MONTH.value:
        return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def to_policy(row: BudgetPolicyModel) -> BudgetPolicy:
    mode = effective_mode(row)
    if row.mode != BudgetMode.ENFORCE.value:
        approval = BudgetApprovalStatus.NOT_REQUIRED
    elif row.approved_at is None:
        approval = BudgetApprovalStatus.PENDING
    else:
        approval = BudgetApprovalStatus.APPROVED
    return BudgetPolicy.model_validate(
        dict(
            id=row.id,
            project_id=row.project_id,
            mode=row.mode,
            period=row.period,
            currency=row.currency,
            cost_limit=row.cost_limit,
            token_limit=row.token_limit,
            max_active_launches=row.max_active_launches,
            reservation_cost=row.reservation_cost,
            reservation_tokens=row.reservation_tokens,
            unknown_cost=row.unknown_cost,
            late_usage=row.late_usage,
            settle_after_seconds=row.settle_after_seconds,
            alert_thresholds=row.alert_thresholds,
            approval_status=approval,
            effective_mode=mode,
            ceiling_guarantee=_guarantee(mode),
            proposed_by_user_id=row.proposed_by_user_id,
            approved_by_user_id=row.approved_by_user_id,
            approved_at=row.approved_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            version=row.version,
        )
    )


def to_reservation(row: BudgetReservationModel) -> BudgetReservation:
    return BudgetReservation.model_validate(
        dict(
            id=row.id,
            task_launch_id=row.task_launch_id,
            status=row.status,
            reserved_cost=row.reserved_cost,
            reserved_tokens=row.reserved_tokens,
            settle_basis=row.settle_basis,
            alerts=row.alerts or [],
            created_at=row.created_at,
            settled_at=row.settled_at,
        )
    )


def _ensure_policy_writer(principal: Principal, project_id: uuid.UUID) -> None:
    if get_launch_scope(principal.machine) is not None:
        raise forbidden("budget_policy", "write")
    ensure_project_access(principal, project_id, "write")
    ensure_can_write(principal, "budget_policy")


async def _get_policy(
    session: AsyncSession, project_id: uuid.UUID, *, lock: bool = False
) -> BudgetPolicyModel | None:
    stmt = select(BudgetPolicyModel).where(BudgetPolicyModel.project_id == project_id)
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt.execution_options(populate_existing=True))
    return result.scalar_one_or_none()


def _same_creation(row: BudgetPolicyModel, principal: Principal, values: dict[str, Any]) -> bool:
    return (
        row.version == 1
        and row.proposed_by_user_id == principal.user.id
        and all(getattr(row, name) == value for name, value in values.items())
    )


async def put_policy(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    update: BudgetPolicyUpdate,
) -> BudgetPolicyModel:
    """Create or replace the project's policy. Any write of an `enforce`
    policy clears its approval: the stored mode only applies once approved."""
    _ensure_policy_writer(principal, project_id)
    if await session.get(ProjectModel, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    values = update.model_dump(exclude={"expected_version"}, mode="python")
    values["mode"] = update.mode.value
    values["period"] = update.period.value
    values["unknown_cost"] = update.unknown_cost.value
    values["late_usage"] = update.late_usage.value
    row = await _get_policy(session, project_id, lock=True)
    if row is not None and update.expected_version is None:
        if not _same_creation(row, principal, values):
            raise _conflict("version_conflict", server_version=row.version)
        await session.commit()
        return row
    if row is None:
        if update.expected_version is not None:
            raise _conflict("version_conflict", server_version=0)
        await session.execute(
            pg_insert(BudgetPolicyModel)
            .values(
                id=uuid.uuid4(),
                project_id=project_id,
                proposed_by_user_id=principal.user.id,
                version=1,
                **values,
            )
            .on_conflict_do_nothing(constraint="uq_budget_policies_project")
        )
        row = await _get_policy(session, project_id, lock=True)
        assert row is not None
        if not _same_creation(row, principal, values):
            raise _conflict("version_conflict", server_version=row.version)
    else:
        if update.expected_version != row.version:
            raise _conflict("version_conflict", server_version=row.version)
        for name, value in values.items():
            setattr(row, name, value)
        row.proposed_by_user_id = principal.user.id
        row.version += 1
    row.approved_by_user_id = None
    row.approved_at = None
    await session.commit()
    await session.refresh(row)
    return row


async def approve_policy(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    approve: BudgetPolicyApprove,
) -> BudgetPolicyModel:
    """An explicit admin approval is what turns a stored `enforce` policy
    into an effective one — never the write that proposed it."""
    _ensure_policy_writer(principal, project_id)
    if principal.role != Role.ADMIN:
        raise forbidden("budget_policy", "approve")
    row = await _get_policy(session, project_id, lock=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "budget policy not found")
    if row.version != approve.expected_version:
        raise _conflict("version_conflict", server_version=row.version)
    if row.mode != BudgetMode.ENFORCE.value or row.approved_at is not None:
        raise _conflict("budget_approval_not_pending")
    row.approved_by_user_id = principal.user.id
    row.approved_at = datetime.now(UTC)
    row.version += 1
    await session.commit()
    await session.refresh(row)
    return row


@dataclass
class _LaunchUsage:
    cost: Decimal = _ZERO
    cost_known: int = 0
    cost_unknown: int = 0
    tokens: Decimal = _ZERO
    tokens_known: int = 0
    tokens_unknown: int = 0


@dataclass
class _Meters:
    consumed: dict[BudgetMetric, Decimal] = field(
        default_factory=lambda: {BudgetMetric.COST: _ZERO, BudgetMetric.TOKENS: _ZERO}
    )
    held: dict[BudgetMetric, Decimal] = field(
        default_factory=lambda: {BudgetMetric.COST: _ZERO, BudgetMetric.TOKENS: _ZERO}
    )
    unknown: dict[BudgetMetric, int] = field(
        default_factory=lambda: {BudgetMetric.COST: 0, BudgetMetric.TOKENS: 0}
    )
    active: int = 0


def _usage_columns(currency: str) -> tuple[Any, ...]:
    entry = UsageLedgerEntryModel
    cost_known = and_(entry.cost_coverage != _UNKNOWN, entry.cost_currency == currency)
    tokens_known = and_(
        entry.tokens_in_coverage != _UNKNOWN,
        entry.tokens_out_coverage != _UNKNOWN,
        or_(
            entry.cached_tokens_scope != "additional_to_input",
            entry.tokens_cached_coverage != _UNKNOWN,
        ),
    )
    tokens_total = (
        func.coalesce(entry.tokens_in, 0)
        + func.coalesce(entry.tokens_out, 0)
        + case(
            (
                entry.cached_tokens_scope == "additional_to_input",
                func.coalesce(entry.tokens_cached, 0),
            ),
            else_=0,
        )
    )
    return (
        func.coalesce(func.sum(case((cost_known, entry.cost), else_=0)), 0),
        func.count().filter(cost_known),
        func.count().filter(~cost_known),
        func.coalesce(func.sum(case((tokens_known, tokens_total), else_=0)), 0),
        func.count().filter(tokens_known),
        func.count().filter(~tokens_known),
    )


def _row_usage(values: Any) -> _LaunchUsage:
    return _LaunchUsage(
        cost=Decimal(values[0]),
        cost_known=int(values[1]),
        cost_unknown=int(values[2]),
        tokens=Decimal(values[3]),
        tokens_known=int(values[4]),
        tokens_unknown=int(values[5]),
    )


def _window_reservations(policy: BudgetPolicyModel, start: datetime | None) -> Select[Any]:
    stmt = select(BudgetReservationModel).where(
        BudgetReservationModel.project_id == policy.project_id
    )
    if start is not None:
        stmt = stmt.where(BudgetReservationModel.created_at >= start)
    return stmt


def _charge(
    reservation: BudgetReservationModel,
    reserved: Decimal,
    actual: Decimal,
    known: int,
    unknown: int,
    policy: BudgetPolicyModel,
) -> Decimal:
    if reservation.status == _HELD:
        return max(actual, reserved)
    if unknown and policy.unknown_cost == UnknownCostPolicy.CHARGE_RESERVATION.value:
        return max(actual, reserved)
    if not known and reservation.settle_basis == SettleBasis.RESERVATION.value:
        return reserved
    return actual


async def _meters(
    session: AsyncSession, policy: BudgetPolicyModel, start: datetime | None, now: datetime
) -> tuple[_Meters, list[BudgetReservationModel]]:
    reservations = list(
        (
            await session.scalars(
                _window_reservations(policy, start).execution_options(populate_existing=True)
            )
        ).all()
    )
    launch_ids = [r.task_launch_id for r in reservations]
    usage: dict[uuid.UUID, _LaunchUsage] = {}
    if launch_ids:
        rows = await session.execute(
            select(UsageLedgerEntryModel.task_launch_id, *_usage_columns(policy.currency))
            .where(
                UsageLedgerEntryModel.project_id == policy.project_id,
                UsageLedgerEntryModel.task_launch_id.in_(launch_ids),
            )
            .group_by(UsageLedgerEntryModel.task_launch_id)
        )
        usage = {row[0]: _row_usage(row[1:]) for row in rows}
    meters = _Meters()
    for reservation in reservations:
        spent = usage.get(reservation.task_launch_id, _LaunchUsage())
        for metric, reserved, actual, known, unknown in (
            (
                BudgetMetric.COST,
                reservation.reserved_cost or _ZERO,
                spent.cost,
                spent.cost_known,
                spent.cost_unknown,
            ),
            (
                BudgetMetric.TOKENS,
                Decimal(reservation.reserved_tokens or 0),
                spent.tokens,
                spent.tokens_known,
                spent.tokens_unknown,
            ),
        ):
            charge = _charge(reservation, reserved, actual, known, unknown, policy)
            outstanding = max(_ZERO, reserved - actual) if reservation.status == _HELD else _ZERO
            meters.held[metric] += outstanding
            meters.consumed[metric] += charge - outstanding
            meters.unknown[metric] += unknown
    reserved_launch = exists().where(
        BudgetReservationModel.task_launch_id == UsageLedgerEntryModel.task_launch_id
    )
    outside = select(*_usage_columns(policy.currency)).where(
        UsageLedgerEntryModel.project_id == policy.project_id,
        or_(UsageLedgerEntryModel.task_launch_id.is_(None), ~reserved_launch),
    )
    if start is not None:
        outside = outside.where(UsageLedgerEntryModel.period_start >= start)
    loose = _row_usage((await session.execute(outside)).one())
    meters.consumed[BudgetMetric.COST] += loose.cost
    meters.consumed[BudgetMetric.TOKENS] += loose.tokens
    meters.unknown[BudgetMetric.COST] += loose.cost_unknown
    meters.unknown[BudgetMetric.TOKENS] += loose.tokens_unknown
    meters.active = await _active_launches(session, policy.project_id, now)
    return meters, reservations


async def _active_launches(session: AsyncSession, project_id: uuid.UUID, now: datetime) -> int:
    """Slots in use: held reservations whose launch is still live. A launch
    past `expires_at` (its machine crashed or vanished) frees its slot even
    before the lazy expiry writes it."""
    count = await session.scalar(
        select(func.count())
        .select_from(BudgetReservationModel)
        .join(TaskLaunchModel, TaskLaunchModel.id == BudgetReservationModel.task_launch_id)
        .where(
            BudgetReservationModel.project_id == project_id,
            BudgetReservationModel.status == _HELD,
            TaskLaunchModel.status.notin_(_TERMINAL),
            TaskLaunchModel.expires_at > now,
        )
    )
    return int(count or 0)


def _never_ran(launch: TaskLaunchModel) -> bool:
    return launch.session_id is None and (
        launch.status in _NEVER_PULLED
        or launch.reason_code == TaskLaunchReasonCode.EXPIRED_UNPULLED.value
    )


async def reconcile(session: AsyncSession, policy: BudgetPolicyModel, now: datetime) -> int:
    """Settle every held reservation whose run is over (terminal, or overdue
    after a crash), per the displayed policy. Deterministic and idempotent:
    replaying it after a crash settles the same rows the same way. Runs with
    the policy row locked. Returns the number of rows settled or released."""
    rows = await session.execute(
        select(BudgetReservationModel, TaskLaunchModel)
        .join(TaskLaunchModel, TaskLaunchModel.id == BudgetReservationModel.task_launch_id)
        .where(
            BudgetReservationModel.project_id == policy.project_id,
            BudgetReservationModel.status == _HELD,
            or_(TaskLaunchModel.status.in_(_TERMINAL), TaskLaunchModel.expires_at <= now),
        )
        .with_for_update(of=BudgetReservationModel)
    )
    pending = list(rows.tuples())
    if not pending:
        return 0
    reported = set(
        (
            await session.scalars(
                select(UsageLedgerEntryModel.task_launch_id)
                .where(
                    UsageLedgerEntryModel.task_launch_id.in_([launch.id for _, launch in pending])
                )
                .distinct()
            )
        ).all()
    )
    settled = 0
    grace = timedelta(seconds=policy.settle_after_seconds)
    for reservation, launch in pending:
        ended = launch.finished_at or launch.expires_at
        if launch.id in reported:
            reservation.status = BudgetReservationStatus.SETTLED.value
            reservation.settle_basis = SettleBasis.MEASURED.value
        elif _never_ran(launch):
            reservation.status = BudgetReservationStatus.RELEASED.value
            reservation.settle_basis = SettleBasis.NONE.value
        elif ended + grace > now:
            continue
        elif policy.late_usage == LateUsagePolicy.HOLD_RESERVATION.value:
            reservation.status = BudgetReservationStatus.SETTLED.value
            reservation.settle_basis = SettleBasis.RESERVATION.value
        else:
            reservation.status = BudgetReservationStatus.RELEASED.value
            reservation.settle_basis = SettleBasis.NONE.value
        reservation.settled_at = now
        reservation.version += 1
        settled += 1
    await session.flush()
    return settled


def _limits(policy: BudgetPolicyModel) -> list[tuple[BudgetMetric, Decimal, Decimal]]:
    limits: list[tuple[BudgetMetric, Decimal, Decimal]] = []
    if policy.cost_limit is not None:
        limits.append((BudgetMetric.COST, policy.cost_limit, policy.reservation_cost or _ZERO))
    if policy.token_limit is not None:
        limits.append(
            (
                BudgetMetric.TOKENS,
                Decimal(policy.token_limit),
                Decimal(policy.reservation_tokens or 0),
            )
        )
    return limits


_REFUSALS = {
    BudgetMetric.COST: BudgetRefusalReason.COST_EXHAUSTED,
    BudgetMetric.TOKENS: BudgetRefusalReason.TOKENS_EXHAUSTED,
    BudgetMetric.SLOTS: BudgetRefusalReason.SLOTS_EXHAUSTED,
}


@dataclass(frozen=True)
class Admission:
    """A verdict ready to be written with the launch: what to reserve and the
    alerts raised. `None` policy = no budget, nothing reserved."""

    policy_id: uuid.UUID
    reserved_cost: Decimal | None
    reserved_tokens: int | None
    alerts: list[BudgetAlert]


def _refuse(
    metric: BudgetMetric,
    limit: Decimal,
    consumed: Decimal,
    held: Decimal,
    requested: Decimal,
    start: datetime | None,
) -> HTTPException:
    detail = BudgetRefusal(
        reason=_REFUSALS[metric],
        metric=metric,
        limit=limit,
        consumed=consumed,
        held=held,
        requested=requested,
        period_start=start,
    )
    return HTTPException(status.HTTP_409_CONFLICT, detail=detail.model_dump(mode="json"))


async def decide_admission(
    session: AsyncSession, project_id: uuid.UUID, now: datetime
) -> Admission | None:
    """Lock the project's policy, reconcile finished runs, then admit or
    refuse. Raises `409 budget_refused` only under an approved `enforce`
    policy; otherwise every limit crossed becomes an alert. The caller writes
    the launch and its reservation in the same transaction."""
    policy = await _get_policy(session, project_id, lock=True)
    if policy is None:
        return None
    await reconcile(session, policy, now)
    start = period_start(policy.period, now)
    meters, _ = await _meters(session, policy, start, now)
    mode = effective_mode(policy)
    alerts: list[BudgetAlert] = []
    if policy.mode == BudgetMode.ENFORCE.value and mode is BudgetMode.ALERT_ONLY:
        alerts.append(BudgetAlert(code=BudgetAlertCode.ENFORCE_PENDING_APPROVAL))
    if policy.max_active_launches is not None and meters.active >= policy.max_active_launches:
        if mode is BudgetMode.ENFORCE:
            raise _refuse(
                BudgetMetric.SLOTS,
                Decimal(policy.max_active_launches),
                Decimal(meters.active),
                _ZERO,
                Decimal(1),
                start,
            )
        alerts.append(BudgetAlert(code=BudgetAlertCode.SLOTS_EXHAUSTED, metric=BudgetMetric.SLOTS))
    for metric, limit, requested in _limits(policy):
        consumed, held = meters.consumed[metric], meters.held[metric]
        before = consumed + held
        after = before + requested
        if after > limit:
            if mode is BudgetMode.ENFORCE:
                raise _refuse(metric, limit, consumed, held, requested, start)
            alerts.append(BudgetAlert(code=BudgetAlertCode.LIMIT_EXCEEDED, metric=metric))
        for threshold in policy.alert_thresholds:
            mark = limit * threshold / 100
            if before < mark <= after or (before == after and after >= mark and threshold == 100):
                alerts.append(
                    BudgetAlert(
                        code=BudgetAlertCode.THRESHOLD_REACHED, metric=metric, threshold=threshold
                    )
                )
        if meters.unknown[metric]:
            alerts.append(BudgetAlert(code=BudgetAlertCode.UNKNOWN_USAGE, metric=metric))
    return Admission(
        policy_id=policy.id,
        reserved_cost=policy.reservation_cost,
        reserved_tokens=policy.reservation_tokens,
        alerts=alerts,
    )


async def record_reservation(
    session: AsyncSession, project_id: uuid.UUID, launch_id: uuid.UUID, admission: Admission
) -> BudgetReservationModel:
    """Write the admitted reservation, once per launch: a replay of the same
    admission returns the existing row instead of holding twice."""
    await session.execute(
        pg_insert(BudgetReservationModel)
        .values(
            id=uuid.uuid4(),
            project_id=project_id,
            policy_id=admission.policy_id,
            task_launch_id=launch_id,
            status=_HELD,
            reserved_cost=admission.reserved_cost,
            reserved_tokens=admission.reserved_tokens,
            alerts=[a.model_dump(mode="json", exclude_none=True) for a in admission.alerts],
            version=1,
        )
        .on_conflict_do_nothing(constraint="uq_budget_reservations_launch")
    )
    row = await session.scalar(
        select(BudgetReservationModel).where(BudgetReservationModel.task_launch_id == launch_id)
    )
    assert row is not None
    return row


async def build_status(session: AsyncSession, project_id: uuid.UUID, now: datetime) -> BudgetStatus:
    policy = await _get_policy(session, project_id)
    if policy is None:
        return BudgetStatus(project_id=project_id)
    start = period_start(policy.period, now)
    meters, reservations = await _meters(session, policy, start, now)
    limits = {metric: limit for metric, limit, _ in _limits(policy)}
    meter_list = [
        BudgetMeter(
            metric=metric,
            limit=limits[metric],
            consumed=meters.consumed[metric],
            held=meters.held[metric],
            unknown_entries=meters.unknown[metric],
        )
        for metric in (BudgetMetric.COST, BudgetMetric.TOKENS)
        if metric in limits
    ]
    if policy.max_active_launches is not None:
        meter_list.append(
            BudgetMeter(
                metric=BudgetMetric.SLOTS,
                limit=Decimal(policy.max_active_launches),
                consumed=Decimal(meters.active),
                held=_ZERO,
            )
        )
    recent = sorted(reservations, key=lambda r: (r.status != _HELD, -r.created_at.timestamp()))[
        :BUDGET_STATUS_MAX_RESERVATIONS
    ]
    mode = effective_mode(policy)
    return BudgetStatus(
        project_id=project_id,
        policy=to_policy(policy),
        effective_mode=mode,
        ceiling_guarantee=_guarantee(mode),
        period_start=start,
        meters=meter_list,
        active_launches=meters.active,
        reservations=[to_reservation(r) for r in recent],
    )


async def get_status(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> BudgetStatus:
    ensure_project_access(principal, project_id)
    if await session.get(ProjectModel, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return await build_status(session, project_id, datetime.now(UTC))


async def reconcile_project(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> BudgetStatus:
    """Explicit reconciliation (crash recovery without waiting for the next
    admission). Same lock and rules as an admission."""
    _ensure_policy_writer(principal, project_id)
    now = datetime.now(UTC)
    policy = await _get_policy(session, project_id, lock=True)
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "budget policy not found")
    await reconcile(session, policy, now)
    await session.commit()
    return await build_status(session, project_id, now)
