from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.infra import InfraMeasurementsReport, InfraPoint, InfraSeries

from studio_operator.db import get_session
from studio_operator.schemas import (
    Alert,
    BreakGlassRequest,
    BreakGlassScope,
    CostTotal,
    Dashboard,
    ServiceHealth,
    StorageUsage,
    StudioDetail,
    StudioSummary,
    StudioUsageRow,
    SuspendedStudio,
    UsageReport,
    UsageTotals,
)
from studio_operator.settings import OperatorSettings, get_settings

# Read-only mirrors of the tables owned by the core API. The console package
# deliberately imports nothing from `studio_api`: it is a separate application
# that shares the cluster, not a module of the API.
_metadata = sa.MetaData()

studios = sa.Table(
    "studios",
    _metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("slug", sa.String),
    sa.Column("name", sa.String),
    sa.Column("plan", sa.String),
    sa.Column("status", sa.String),
    sa.Column("is_internal", sa.Boolean),
    sa.Column("suspension_reason", sa.Text),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("version", sa.Integer),
)

studio_memberships = sa.Table(
    "studio_memberships",
    _metadata,
    sa.Column("studio_id", PGUUID(as_uuid=True)),
    sa.Column("user_id", PGUUID(as_uuid=True)),
    sa.Column("role", sa.String),
)

users = sa.Table(
    "users",
    _metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("email", sa.String),
)

projects = sa.Table(
    "projects",
    _metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("studio_id", PGUUID(as_uuid=True)),
)

infra_measurements = sa.Table(
    "infra_measurements",
    _metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("metric", sa.String),
    sa.Column("subject", sa.String),
    sa.Column("project_id", PGUUID(as_uuid=True)),
    sa.Column("value", sa.BigInteger),
    sa.Column("measured_at", sa.DateTime(timezone=True)),
)

usage_ledger_entries = sa.Table(
    "usage_ledger_entries",
    _metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", PGUUID(as_uuid=True)),
    sa.Column("period_start", sa.DateTime(timezone=True)),
    sa.Column("tokens_in", sa.BigInteger),
    sa.Column("tokens_out", sa.BigInteger),
    sa.Column("cost", sa.Numeric(18, 8)),
    sa.Column("cost_currency", sa.String),
    sa.Column("duration_seconds", sa.Numeric(14, 3)),
)

break_glass_requests = sa.Table(
    "break_glass_requests",
    _metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("studio_id", PGUUID(as_uuid=True)),
    sa.Column("operator_ref", sa.Text),
    sa.Column("reason", sa.Text),
    sa.Column("scope", sa.String),
    sa.Column("requested_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.String),
    sa.Column("decided_by_user_id", PGUUID(as_uuid=True)),
    sa.Column("decided_at", sa.DateTime(timezone=True)),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
)

break_glass_audit = sa.Table(
    "break_glass_audit",
    _metadata,
    sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
    sa.Column("event", sa.String),
    sa.Column("request_id", PGUUID(as_uuid=True)),
    sa.Column("studio_id", PGUUID(as_uuid=True)),
    sa.Column("actor", sa.Text),
    sa.Column("at", sa.DateTime(timezone=True)),
)

SUSPENDED = "suspended"
ACTIVE = "active"
BREAK_GLASS_REQUEST_WINDOW = timedelta(hours=24)

# Names written by `services/api/src/studio_api/services/http_metrics.py` into
# `infra_measurements`; kept as literals so this separate app imports nothing
# from the core service.
HTTP_REQUESTS = "http_requests"
HTTP_ERRORS_5XX = "http_requests_5xx"
HTTP_LATENCY_P50 = "http_latency_p50_ms"


class ProtectedStudioError(Exception):
    """The internal studio is never suspendable."""


def _percent(used: int, quota: int | None) -> float | None:
    if not quota or quota <= 0:
        return None
    return round(used * 100.0 / quota, 1)


def _money(value: Any) -> str | None:
    if value is None:
        return None
    return f"{Decimal(str(value)):.2f}"


def _as_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _as_float(value: Any) -> float | None:
    return None if value is None else round(float(value), 1)


def _ago(moment: datetime, now: datetime) -> str:
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 3600:
        return f"il y a {max(1, seconds // 60)} min"
    if seconds < 86400:
        return f"il y a {seconds // 3600} h"
    return f"il y a {seconds // 86400} j"


class OperatorRepository:
    """Aggregate reads and the one status write the console is allowed."""

    def __init__(self, session: AsyncSession, settings: OperatorSettings) -> None:
        self.session = session
        self.settings = settings

    # -- reads ---------------------------------------------------------

    async def _latest_storage_by_studio(self) -> dict[uuid.UUID, int]:
        latest = (
            select(
                infra_measurements.c.project_id.label("project_id"),
                infra_measurements.c.value.label("value"),
            )
            .where(
                infra_measurements.c.metric == "storage_bytes",
                infra_measurements.c.project_id.is_not(None),
            )
            .distinct(infra_measurements.c.project_id)
            .order_by(infra_measurements.c.project_id, infra_measurements.c.measured_at.desc())
            .subquery()
        )
        rows = await self.session.execute(
            select(projects.c.studio_id, func.coalesce(func.sum(latest.c.value), 0))
            .join(latest, latest.c.project_id == projects.c.id)
            .group_by(projects.c.studio_id)
        )
        return {row[0]: int(row[1]) for row in rows}

    async def _members_by_studio(self) -> dict[uuid.UUID, int]:
        rows = await self.session.execute(
            select(studio_memberships.c.studio_id, func.count()).group_by(
                studio_memberships.c.studio_id
            )
        )
        return {row[0]: int(row[1]) for row in rows}

    async def _owners_by_studio(self) -> dict[uuid.UUID, str]:
        rows = await self.session.execute(
            select(studio_memberships.c.studio_id, func.min(users.c.email))
            .join(users, users.c.id == studio_memberships.c.user_id)
            .where(studio_memberships.c.role == "owner")
            .group_by(studio_memberships.c.studio_id)
        )
        return {row[0]: str(row[1]) for row in rows if row[1] is not None}

    async def _http_metrics(self, since: datetime) -> tuple[int | None, int | None, int | None]:
        """(requests, 5xx, median hourly p50) over the window, or None values.

        Duplicate rows for one hour (two processes, a restart) collapse on
        `max(value)`: each row already carries that hour's total, never an
        increment, so summing them would double count."""
        rows = await self.session.execute(
            select(
                infra_measurements.c.metric,
                func.max(infra_measurements.c.value),
            )
            .where(
                infra_measurements.c.metric.in_((HTTP_REQUESTS, HTTP_ERRORS_5XX, HTTP_LATENCY_P50)),
                infra_measurements.c.measured_at >= since,
            )
            .group_by(infra_measurements.c.metric, infra_measurements.c.subject)
        )
        requests = errors = 0
        p50_values: list[int] = []
        measured = False
        for metric, value in rows:
            measured = True
            if metric == HTTP_REQUESTS:
                requests += int(value)
            elif metric == HTTP_ERRORS_5XX:
                errors += int(value)
            else:
                p50_values.append(int(value))
        if not measured:
            return None, None, None
        latency = _median(p50_values)
        return requests, errors, latency

    async def platform_storage(self) -> StorageUsage:
        latest = (
            select(infra_measurements.c.value.label("value"))
            .where(
                infra_measurements.c.metric == "storage_bytes",
                infra_measurements.c.project_id.is_not(None),
            )
            .distinct(infra_measurements.c.project_id)
            .order_by(infra_measurements.c.project_id, infra_measurements.c.measured_at.desc())
            .subquery()
        )
        used = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(latest.c.value), 0)).select_from(latest)
            )
            or 0
        )
        capacity = self.settings.storage_capacity_bytes or None
        return StorageUsage(used_bytes=used, quota_bytes=capacity, percent=_percent(used, capacity))

    async def _summaries(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        studio_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[StudioSummary]:
        stmt = select(
            studios.c.id,
            studios.c.name,
            studios.c.slug,
            studios.c.plan,
            studios.c.status,
            studios.c.suspension_reason,
            studios.c.created_at,
        ).order_by(studios.c.name)
        if studio_id is not None:
            stmt = stmt.where(studios.c.id == studio_id)
        if status is not None:
            stmt = stmt.where(studios.c.status == status)
        if query:
            needle = query.strip().lower()
            if needle:
                owner_match = (
                    select(studio_memberships.c.studio_id)
                    .join(users, users.c.id == studio_memberships.c.user_id)
                    .where(
                        studio_memberships.c.role == "owner",
                        func.lower(users.c.email).contains(needle, autoescape=True),
                    )
                )
                stmt = stmt.where(
                    or_(
                        func.lower(studios.c.name).contains(needle, autoescape=True),
                        func.lower(studios.c.slug).contains(needle, autoescape=True),
                        studios.c.id.in_(owner_match),
                    )
                )
        stmt = stmt.limit(limit)

        rows = (await self.session.execute(stmt)).all()
        storage = await self._latest_storage_by_studio()
        members = await self._members_by_studio()
        owners = await self._owners_by_studio()

        result: list[StudioSummary] = []
        for row in rows:
            key = row[0]
            quota = self.settings.quota_for(row[3])
            used = storage.get(key, 0)
            result.append(
                StudioSummary(
                    id=key,
                    name=row[1],
                    slug=row[2],
                    plan=row[3],
                    status=row[4],
                    suspension_reason=row[5],
                    created_at=row[6],
                    owner_email=owners.get(key),
                    storage=StorageUsage(
                        used_bytes=used,
                        quota_bytes=quota.storage_bytes if quota else None,
                        percent=_percent(used, quota.storage_bytes if quota else None),
                    ),
                    members=members.get(key, 0),
                    members_limit=quota.members if quota else None,
                )
            )
        return result

    async def list_studios(
        self, query: str | None = None, *, limit: int = 100
    ) -> list[StudioSummary]:
        return await self._summaries(query=query, limit=limit)

    async def count_studios(self) -> int:
        return int(await self.session.scalar(select(func.count()).select_from(studios)) or 0)

    async def suspended(self) -> list[SuspendedStudio]:
        summaries = await self._summaries(status=SUSPENDED, limit=500)
        if not summaries:
            return []
        ids = [summary.id for summary in summaries]
        rows = await self.session.execute(
            select(studios.c.id, studios.c.updated_at).where(studios.c.id.in_(ids))
        )
        since = {row[0]: row[1] for row in rows}
        return [
            SuspendedStudio(
                id=summary.id,
                name=summary.name,
                slug=summary.slug,
                plan=summary.plan,
                members=summary.members,
                storage=summary.storage,
                owner_email=summary.owner_email,
                suspension_reason=summary.suspension_reason,
                since=since.get(summary.id),
            )
            for summary in summaries
        ]

    async def has_measures(self) -> bool:
        infra = await self.session.scalar(select(infra_measurements.c.value).limit(1))
        if infra is not None:
            return True
        ledger = await self.session.scalar(select(usage_ledger_entries.c.id).limit(1))
        return ledger is not None

    async def dashboard(self, *, now: datetime | None = None) -> Dashboard:
        generated_at = now or datetime.now(UTC)
        since_week = generated_at - timedelta(days=7)
        active = int(
            await self.session.scalar(
                select(func.count()).select_from(studios).where(studios.c.status == ACTIVE)
            )
            or 0
        )
        new_week = int(
            await self.session.scalar(
                select(func.count())
                .select_from(studios)
                .where(studios.c.status == ACTIVE, studios.c.created_at >= since_week)
            )
            or 0
        )
        storage = await self.platform_storage()
        requests_24h, errors_24h, latency_p50 = await self._http_metrics(
            generated_at - timedelta(hours=24)
        )
        error_rate = _error_rate(requests_24h, errors_24h)

        backup_at: datetime | None = await self.session.scalar(
            select(infra_measurements.c.measured_at)
            .where(infra_measurements.c.metric == "backup_bytes")
            .order_by(infra_measurements.c.measured_at.desc())
            .limit(1)
        )
        database = (
            ServiceHealth(
                key="database",
                label="Base de données",
                state="ok",
                detail=f"Dernière sauvegarde {_ago(backup_at, generated_at)}",
                measured_at=backup_at,
            )
            if backup_at is not None
            else ServiceHealth(
                key="database",
                label="Base de données",
                state="unavailable",
                detail="Aucune sauvegarde mesurée",
            )
        )

        if requests_24h is None:
            api = ServiceHealth(
                key="api",
                label="API",
                state="unavailable",
                detail="Aucun comptage HTTP encore",
            )
        elif error_rate is not None and error_rate >= 1.0:
            api = ServiceHealth(
                key="api",
                label="API",
                state="degraded",
                detail=f"{error_rate:g} % d'erreurs 5xx (24 h)",
            )
        elif latency_p50 is not None:
            api = ServiceHealth(
                key="api",
                label="API",
                state="ok",
                detail=f"Réponse médiane {latency_p50} ms",
            )
        else:
            api = ServiceHealth(
                key="api",
                label="API",
                state="ok",
                detail="Comptage actif, latence non mesurée",
            )

        services = [
            api,
            database,
            ServiceHealth(
                key="stripe_webhooks",
                label="Webhooks Stripe",
                state="unavailable",
                detail="Facturation Stripe (S4) non déployée",
            ),
        ]

        alerts: list[Alert] = []
        if storage.percent is not None and storage.percent >= self.settings.storage_alert_percent:
            alerts.append(
                Alert(
                    level="warning",
                    title=f"Stockage à {storage.percent:g} % de la capacité",
                    detail=(
                        f"Le seuil d'alerte ({self.settings.storage_alert_percent} %) "
                        "est franchi. Étendre le volume."
                    ),
                )
            )

        return Dashboard(
            generated_at=generated_at,
            active_studios=active,
            new_studios_7d=new_week,
            storage=storage,
            error_rate_5xx_24h=error_rate,
            api_latency_p50_ms=latency_p50,
            unpaid_in_grace=None,
            services=services,
            alerts=alerts,
            has_measures=await self.has_measures(),
        )

    async def _usage_by_studio(self, since: datetime) -> dict[uuid.UUID, UsageTotals]:
        rows = await self.session.execute(
            select(
                projects.c.studio_id,
                func.sum(usage_ledger_entries.c.tokens_in),
                func.sum(usage_ledger_entries.c.tokens_out),
                func.sum(usage_ledger_entries.c.cost),
                usage_ledger_entries.c.cost_currency,
                func.sum(usage_ledger_entries.c.duration_seconds),
            )
            .join(projects, projects.c.id == usage_ledger_entries.c.project_id)
            .where(usage_ledger_entries.c.period_start >= since)
            .group_by(projects.c.studio_id, usage_ledger_entries.c.cost_currency)
        )
        totals: dict[uuid.UUID, UsageTotals] = {}
        for row in rows:
            entry = totals.setdefault(row[0], UsageTotals())
            entry.tokens_in = _merge_int(entry.tokens_in, _as_int(row[1]))
            entry.tokens_out = _merge_int(entry.tokens_out, _as_int(row[2]))
            entry.duration_seconds = _merge_float(entry.duration_seconds, _as_float(row[5]))
            amount = _money(row[3])
            currency = row[4]
            if amount is not None and currency:
                entry.costs.append(CostTotal(currency=str(currency), amount=amount))
        return totals

    @staticmethod
    def _merge_totals(target: UsageTotals, source: UsageTotals) -> None:
        target.tokens_in = _merge_int(target.tokens_in, source.tokens_in)
        target.tokens_out = _merge_int(target.tokens_out, source.tokens_out)
        target.duration_seconds = _merge_float(target.duration_seconds, source.duration_seconds)
        for cost in source.costs:
            _add_cost(target.costs, cost.currency, cost.amount)

    async def usage(self, days: int, *, now: datetime | None = None) -> UsageReport:
        generated_at = now or datetime.now(UTC)
        since = generated_at - timedelta(days=days)
        summaries = await self._summaries(limit=500)
        by_studio = await self._usage_by_studio(since)

        totals = UsageTotals()
        rows: list[StudioUsageRow] = []
        for summary in summaries:
            usage = by_studio.get(summary.id, UsageTotals())
            self._merge_totals(totals, usage)
            rows.append(
                StudioUsageRow(
                    id=summary.id,
                    name=summary.name,
                    plan=summary.plan,
                    status=summary.status,
                    storage=summary.storage,
                    members=summary.members,
                    members_limit=summary.members_limit,
                    usage=usage,
                )
            )

        rows.sort(key=lambda row: -_token_total(row.usage))
        requests, _errors, _latency = await self._http_metrics(since)

        return UsageReport(
            window_days=days,
            generated_at=generated_at,
            studios=await self.count_studios(),
            storage=await self.platform_storage(),
            api_calls=requests,
            totals=totals,
            top_studios=rows[:10],
            over_quota=[
                row
                for row in rows
                if row.storage.percent is not None
                and row.storage.percent >= self.settings.usage_alert_percent
            ],
            has_measures=await self.has_measures(),
        )

    async def studio_detail(
        self, studio_id: uuid.UUID, *, days: int = 30, now: datetime | None = None
    ) -> StudioDetail | None:
        generated_at = now or datetime.now(UTC)
        found = await self._summaries(studio_id=studio_id, limit=1)
        if not found:
            return None
        by_studio = await self._usage_by_studio(generated_at - timedelta(days=days))
        return StudioDetail(
            studio=found[0],
            usage_window_days=days,
            usage=by_studio.get(studio_id, UsageTotals()),
        )

    async def measures(self, days: int, *, now: datetime | None = None) -> InfraMeasurementsReport:
        generated_at = now or datetime.now(UTC)
        since = generated_at - timedelta(days=days)
        rows = await self.session.execute(
            select(
                infra_measurements.c.metric,
                infra_measurements.c.subject,
                infra_measurements.c.project_id,
                infra_measurements.c.measured_at,
                infra_measurements.c.value,
            )
            .where(infra_measurements.c.measured_at >= since)
            .order_by(infra_measurements.c.measured_at)
        )
        grouped: dict[tuple[str, str, uuid.UUID | None], list[InfraPoint]] = {}
        for row in rows:
            key = (str(row[0]), str(row[1]), row[2])
            grouped.setdefault(key, []).append(InfraPoint(measured_at=row[3], value=int(row[4])))
        series = [
            InfraSeries(
                metric=metric,
                subject=subject,
                project_id=project_id,
                latest=points[-1],
                points=points,
            )
            for (metric, subject, project_id), points in sorted(
                grouped.items(), key=lambda item: (item[0][0], item[0][1], str(item[0][2] or ""))
            )
        ]
        return InfraMeasurementsReport(window_days=days, generated_at=generated_at, series=series)

    # -- break-glass (C5) ----------------------------------------------

    async def _expire_due_break_glass(self, now: datetime) -> None:
        rows = (
            await self.session.execute(
                select(break_glass_requests.c.id, break_glass_requests.c.studio_id)
                .where(
                    or_(
                        (
                            (break_glass_requests.c.status == "requested")
                            & (
                                break_glass_requests.c.requested_at
                                <= now - BREAK_GLASS_REQUEST_WINDOW
                            )
                        ),
                        (
                            (break_glass_requests.c.status == "approved")
                            & (break_glass_requests.c.expires_at <= now)
                        ),
                    )
                )
                .with_for_update()
            )
        ).all()
        if not rows:
            return
        ids = [row[0] for row in rows]
        await self.session.execute(
            update(break_glass_requests)
            .where(break_glass_requests.c.id.in_(ids))
            .values(status="expired")
        )
        await self.session.execute(
            insert(break_glass_audit),
            [
                {
                    "id": uuid.uuid4(),
                    "event": "expired",
                    "request_id": row[0],
                    "studio_id": row[1],
                    "actor": "system",
                    "at": now,
                }
                for row in rows
            ],
        )
        await self.session.commit()

    async def break_glass_queue(self, *, limit: int = 100) -> list[BreakGlassRequest]:
        now = datetime.now(UTC)
        await self._expire_due_break_glass(now)
        rows = (
            await self.session.execute(
                select(
                    break_glass_requests.c.id,
                    break_glass_requests.c.studio_id,
                    studios.c.name,
                    break_glass_requests.c.operator_ref,
                    break_glass_requests.c.reason,
                    break_glass_requests.c.scope,
                    break_glass_requests.c.status,
                    break_glass_requests.c.requested_at,
                    break_glass_requests.c.decided_at,
                    break_glass_requests.c.expires_at,
                )
                .join(studios, studios.c.id == break_glass_requests.c.studio_id)
                .order_by(
                    break_glass_requests.c.requested_at.desc(),
                    break_glass_requests.c.id.desc(),
                )
                .limit(limit)
            )
        ).all()
        return [
            BreakGlassRequest(
                id=row[0],
                studio_id=row[1],
                studio_name=row[2],
                operator_ref=row[3],
                reason=row[4],
                scope=row[5],
                status=row[6],
                requested_at=row[7],
                decided_at=row[8],
                expires_at=row[9],
            )
            for row in rows
        ]

    async def request_break_glass(
        self, studio_id: uuid.UUID, operator_ref: str, reason: str, scope: BreakGlassScope
    ) -> BreakGlassRequest | None:
        studio_name = await self.session.scalar(
            select(studios.c.name).where(studios.c.id == studio_id)
        )
        if studio_name is None:
            return None
        now = datetime.now(UTC)
        request_id = uuid.uuid4()
        await self.session.execute(
            insert(break_glass_requests).values(
                id=request_id,
                studio_id=studio_id,
                operator_ref=operator_ref,
                reason=reason,
                scope=scope,
                requested_at=now,
                status="requested",
            )
        )
        await self.session.execute(
            insert(break_glass_audit).values(
                id=uuid.uuid4(),
                event="requested",
                request_id=request_id,
                studio_id=studio_id,
                actor=f"operator:{operator_ref}",
                at=now,
            )
        )
        await self.session.commit()
        return BreakGlassRequest(
            id=request_id,
            studio_id=studio_id,
            studio_name=studio_name,
            operator_ref=operator_ref,
            reason=reason,
            scope=scope,
            status="requested",
            requested_at=now,
        )

    # -- the only write ------------------------------------------------

    async def set_status(
        self, studio_id: uuid.UUID, new_status: str, reason: str | None = None
    ) -> StudioSummary | None:
        row = (
            await self.session.execute(
                select(studios.c.is_internal).where(studios.c.id == studio_id)
            )
        ).first()
        if row is None:
            return None
        if row[0]:
            raise ProtectedStudioError(str(studio_id))
        await self.session.execute(
            update(studios)
            .where(studios.c.id == studio_id)
            .values(
                status=new_status,
                suspension_reason=reason if new_status == SUSPENDED else None,
                version=studios.c.version + 1,
                updated_at=func.now(),
            )
        )
        await self.session.commit()
        found = await self._summaries(studio_id=studio_id, limit=1)
        return found[0] if found else None


def _merge_int(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _merge_float(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return round(left + right, 1)


def _add_cost(costs: list[CostTotal], currency: str, amount: str) -> None:
    for cost in costs:
        if cost.currency == currency:
            cost.amount = f"{Decimal(cost.amount) + Decimal(amount):.2f}"
            return
    costs.append(CostTotal(currency=currency, amount=amount))


def _token_total(totals: UsageTotals) -> int:
    return (totals.tokens_in or 0) + (totals.tokens_out or 0)


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return int(round((ordered[middle - 1] + ordered[middle]) / 2))


def _error_rate(requests: int | None, errors: int | None) -> float | None:
    if not requests or errors is None:
        return None
    return round(errors * 100.0 / requests, 1)


def get_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[OperatorSettings, Depends(get_settings)],
) -> OperatorRepository:
    return OperatorRepository(session, settings)
