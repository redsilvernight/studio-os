"""Declared subscriptions and their read-time share of usage (DEC-0361)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.usage import (
    UsageCurrencyAmount,
    UsageSubscription,
    UsageSubscriptionCreate,
    UsageSubscriptionFields,
    UsageSubscriptionShare,
    UsageSubscriptionUpdate,
    UsageTotalStatus,
)

from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.usage import UsageLedgerEntryModel, UsageSubscriptionModel
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_project_access,
    forbidden,
    get_launch_scope,
)

_SHARE_QUANTUM = Decimal("0.000001")


@dataclass
class ShareAccumulator:
    by_currency: dict[str, Decimal] = field(default_factory=dict)
    entries_by_currency: dict[str, int] = field(default_factory=dict)
    estimated: int = 0
    unknown: int = 0
    provisional: bool = False

    def add(self, currency: str, amount: Decimal, entries: int, provisional: bool) -> None:
        self.by_currency[currency] = self.by_currency.get(currency, Decimal(0)) + amount
        self.entries_by_currency[currency] = self.entries_by_currency.get(currency, 0) + entries
        self.estimated += entries
        self.provisional = self.provisional or provisional

    def merge(self, other: ShareAccumulator) -> None:
        for currency, amount in other.by_currency.items():
            self.by_currency[currency] = self.by_currency.get(currency, Decimal(0)) + amount
            self.entries_by_currency[currency] = (
                self.entries_by_currency.get(currency, 0) + other.entries_by_currency[currency]
            )
        self.estimated += other.estimated
        self.unknown += other.unknown
        self.provisional = self.provisional or other.provisional

    def finalize(self) -> UsageSubscriptionShare:
        by_currency = [
            UsageCurrencyAmount(
                currency=currency,
                known_sum=amount.quantize(_SHARE_QUANTUM),
                entries=self.entries_by_currency[currency],
            )
            for currency, amount in sorted(self.by_currency.items())
        ]
        if len(by_currency) > 1:
            share_status = UsageTotalStatus.MIXED_CURRENCY
        elif not by_currency:
            share_status = UsageTotalStatus.UNKNOWN if self.unknown else UsageTotalStatus.NONE
        else:
            share_status = UsageTotalStatus.PARTIAL if self.unknown else UsageTotalStatus.ESTIMATED
        single = by_currency[0] if len(by_currency) == 1 else None
        return UsageSubscriptionShare(
            status=share_status,
            known_sum=single.known_sum if single is not None else None,
            currency=single.currency if single is not None else None,
            by_currency=by_currency,
            provisional=self.provisional,
            estimated_entries=self.estimated,
            unknown_entries=self.unknown,
        )


def _month_start(value: datetime | date) -> date:
    return date(value.year, value.month, 1)


def _next_month(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def _as_timestamp(month: date) -> datetime:
    return datetime(month.year, month.month, 1)


def _active(subscription: UsageSubscriptionModel, month: date) -> bool:
    return subscription.starts_on < _next_month(month) and (
        subscription.ends_on is None or subscription.ends_on >= month
    )


def _covers(
    subscription: UsageSubscriptionModel, harness: str | None, provider: str | None
) -> bool:
    if subscription.harnesses and harness not in subscription.harnesses:
        return False
    return not subscription.providers or provider in subscription.providers


async def subscription_shares(
    session: AsyncSession,
    project_id: uuid.UUID,
    groups: dict[str, Any],
    scope: Sequence[Any],
    *,
    join_task: bool,
    now: datetime,
) -> dict[tuple[Any, ...], ShareAccumulator] | None:
    """Share of each declared subscription per summary group, or `None` when the
    project declares none. A subscription's monthly price is spread over the
    covered entries of each UTC month it is active — whole project, every
    machine — pro rata of their cost; the groups in scope get their entries'
    part. A month whose covered costs span several currencies or sum to zero
    is not split: its covered entries count as unknown."""

    subscriptions = list(
        (
            await session.scalars(
                select(UsageSubscriptionModel).where(
                    UsageSubscriptionModel.project_id == project_id
                )
            )
        ).all()
    )
    if not subscriptions:
        return None
    entry = UsageLedgerEntryModel
    month = func.date_trunc("month", func.timezone("UTC", entry.period_start))
    dimensions = [*groups.values(), month, entry.harness, entry.provider, entry.cost_currency]
    stmt = select(*dimensions, func.count(), func.sum(entry.cost)).where(
        entry.project_id == project_id, *scope
    )
    if join_task:
        stmt = stmt.outerjoin(TaskModel, TaskModel.id == entry.task_id)
    rows = (await session.execute(stmt.group_by(*dimensions))).all()
    shares: dict[tuple[Any, ...], ShareAccumulator] = {}
    if not rows:
        return shares
    months = {_month_start(row[len(groups)]) for row in rows}
    total_dimensions = [month, entry.harness, entry.provider, entry.cost_currency]
    totals = (
        await session.execute(
            select(*total_dimensions, func.sum(entry.cost))
            .where(
                entry.project_id == project_id,
                entry.cost.is_not(None),
                month >= _as_timestamp(min(months)),
                month < _as_timestamp(_next_month(max(months))),
            )
            .group_by(*total_dimensions)
        )
    ).all()
    current = _month_start(now)
    for subscription in subscriptions:
        for covered_month in sorted(months):
            if not _active(subscription, covered_month):
                continue
            _allocate(subscription, covered_month, groups, rows, totals, shares, current)
    return shares


def _allocate(
    subscription: UsageSubscriptionModel,
    covered_month: date,
    groups: dict[str, Any],
    rows: Iterable[Any],
    totals: Iterable[Any],
    shares: dict[tuple[Any, ...], ShareAccumulator],
    current: date,
) -> None:
    month_total: dict[str, Decimal] = defaultdict(Decimal)
    for row_month, harness, provider, currency, amount in totals:
        if _month_start(row_month) == covered_month and _covers(subscription, harness, provider):
            month_total[currency] += Decimal(amount)
    divisor = next(iter(month_total.values())) if len(month_total) == 1 else Decimal(0)
    for row in rows:
        key_values = tuple(row[: len(groups)])
        row_month, harness, provider, currency, count, amount = row[len(groups) :]
        if _month_start(row_month) != covered_month or not _covers(subscription, harness, provider):
            continue
        share = shares.setdefault(key_values, ShareAccumulator())
        if currency is None or divisor <= 0:
            share.unknown += count
            continue
        share.add(
            subscription.currency,
            subscription.monthly_price * Decimal(amount) / divisor,
            count,
            covered_month == current,
        )


def to_subscription(row: UsageSubscriptionModel) -> UsageSubscription:
    return UsageSubscription.model_validate(row)


def _ensure_manager(principal: Principal, project_id: uuid.UUID) -> None:
    ensure_can_write(principal, "usage_subscription")
    if get_launch_scope(principal.machine) is not None:
        raise forbidden("usage_subscription", "write")
    ensure_project_access(principal, project_id, "write")


def _terms(payload: UsageSubscriptionFields) -> dict[str, Any]:
    return payload.model_dump(
        include={
            "label",
            "monthly_price",
            "currency",
            "harnesses",
            "providers",
            "starts_on",
            "ends_on",
        }
    )


async def list_subscriptions(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[UsageSubscriptionModel]:
    ensure_project_access(principal, project_id)
    stmt = (
        select(UsageSubscriptionModel)
        .where(UsageSubscriptionModel.project_id == project_id)
        .order_by(UsageSubscriptionModel.starts_on, UsageSubscriptionModel.id)
    )
    return list((await session.scalars(stmt)).all())


async def create_subscription(
    session: AsyncSession,
    principal: Principal,
    payload: UsageSubscriptionCreate,
    *,
    commit: bool = True,
) -> UsageSubscriptionModel:
    _ensure_manager(principal, payload.project_id)
    if await session.get(ProjectModel, payload.project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    row = UsageSubscriptionModel(project_id=payload.project_id, **_terms(payload))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    if commit:
        await session.commit()
    return row


async def _locked(
    session: AsyncSession, principal: Principal, subscription_id: uuid.UUID, expected_version: int
) -> UsageSubscriptionModel:
    row = await session.get(UsageSubscriptionModel, subscription_id, with_for_update=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "subscription not found")
    _ensure_manager(principal, row.project_id)
    if row.version != expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "version_conflict", "server_version": row.version},
        )
    return row


async def update_subscription(
    session: AsyncSession,
    principal: Principal,
    subscription_id: uuid.UUID,
    payload: UsageSubscriptionUpdate,
) -> UsageSubscriptionModel:
    row = await _locked(session, principal, subscription_id, payload.expected_version)
    for name, value in _terms(payload).items():
        setattr(row, name, value)
    row.version += 1
    await session.flush()
    await session.refresh(row)
    await session.commit()
    return row


async def delete_subscription(
    session: AsyncSession, principal: Principal, subscription_id: uuid.UUID, expected_version: int
) -> None:
    row = await _locked(session, principal, subscription_id, expected_version)
    await session.delete(row)
    await session.commit()
