"""The one module that reads plans and applies plan limits (S3-droits-plans).

Everything a limit needs lives here: the catalogue read, the per-studio counter
refresh (fed by the phase-M `infra_measurements` collector), the entitlement
view the dashboard consumes, and the single `402 plan_limit_reached` error.

Rules this module owns:

- A number is never hard-coded in an endpoint: `plans` / `plan_limits` decide.
- A limit is enforced only on writes. Reading, listing, downloading and
  exporting never call `enforce_*`, so they can never be blocked by a limit.
- Counters are derived from `infra_measurements` (`measured`) with a live
  fallback (`live`) when the collector has not run yet; they are cached in
  `studio_plan_counters` so a check never rescans the measurement history.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import HTTPException, status
from pydantic import AwareDatetime, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.common import ContractModel

from studio_api.db.models.infra_measurement import InfraMeasurementModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.plan import PlanLimitModel, PlanModel, StudioPlanCounterModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.db.models.transfer import TransferModel
from studio_api.services import event_stream
from studio_api.settings import get_settings

STORAGE_BYTES = "storage_bytes"
FILE_SIZE_BYTES = "file_size_bytes"
SSE_CONNECTIONS = "sse_connections"
PROJECTS = "projects"
MEMBERS = "members"
MACHINES = "machines"
STUDIOS_PER_ACCOUNT = "studios_per_account"
VAULT_VERSIONS_PER_NOTE = "vault_versions_per_note"
REQUESTS_PER_MINUTE = "requests_per_minute"

MEASURED_STORAGE_METRIC = "storage_bytes"
MEASURED_SSE_METRIC = "sse_connections"

_REQUEST_WINDOW_SECONDS = 60.0
_REQUEST_WINDOW_MAX_STUDIOS = 10_000
_request_windows: dict[uuid.UUID, deque[float]] = {}


class PlanSummary(ContractModel):
    """One plan of the catalogue: `code` is the stable machine value stored on
    `studios.plan`, `rank` orders plans from most restricted to most permissive."""

    code: str
    name: str
    rank: int = Field(ge=0)


class PlanLimit(ContractModel):
    """One declared ceiling. `max_value = None` means explicitly unlimited;
    `unit` is a display hint (`bytes`, `days`, `versions`, ...)."""

    key: str
    max_value: int | None = Field(default=None, ge=0)
    unit: str = ""


class StudioCounter(ContractModel):
    """Consumption of one limit for one studio. `source` says where the value
    came from: `measured` (phase-M `infra_measurements`), `live` (direct count)
    or `default` (nothing measured yet)."""

    key: str
    value: int = Field(ge=0)
    source: Literal["measured", "live", "default"] = "live"
    measured_at: AwareDatetime | None = None


class StudioEntitlements(ContractModel):
    """Plan, limits and counters of one studio: exactly what the Subscription
    and Usage screens display. `upgrade_url` is the subscription screen used by
    every `plan_limit_reached` refusal."""

    studio_id: uuid.UUID
    plan: PlanSummary
    limits: list[PlanLimit]
    counters: list[StudioCounter]
    upgrade_url: str
    generated_at: AwareDatetime


def upgrade_url() -> str:
    """Customer-facing subscription screen, the `upgrade_url` of every
    `plan_limit_reached` response."""
    return get_settings().billing_upgrade_url


def plan_limit_reached(
    limit_key: str, *, max_value: int, current: int, requested: int = 0
) -> HTTPException:
    """The single limit error (`402`), shared by every endpoint. `limit` names
    the ceiling and `upgrade_url` the action a human can take; `current` and
    `requested` explain the refusal without exposing another studio's data."""
    return HTTPException(
        status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "error_code": "plan_limit_reached",
            "limit": limit_key,
            "upgrade_url": upgrade_url(),
            "max_value": max_value,
            "current": current,
            "requested": requested,
        },
    )


async def default_plan_code(session: AsyncSession) -> str:
    """The plan a studio falls back to when its stored code is unknown."""
    code = await session.scalar(select(PlanModel.code).where(PlanModel.is_default.is_(True)))
    return code or "free"


async def resolve_plan(session: AsyncSession, code: str | None) -> PlanModel:
    """The catalogue row for `code`, or the default plan when it is unknown."""
    plan = await session.get(PlanModel, code) if code else None
    if plan is None:
        plan = await session.get(PlanModel, await default_plan_code(session))
    if plan is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "plan catalogue is not seeded")
    return plan


async def limits_for_plan(session: AsyncSession, plan_code: str) -> list[PlanLimit]:
    """Declarative limits of one plan, ordered by key. A missing row means the
    plan says nothing about that limit; a row with `max_value = None` means
    explicitly unlimited."""
    rows = (
        await session.execute(
            select(PlanLimitModel)
            .where(PlanLimitModel.plan_code == plan_code)
            .order_by(PlanLimitModel.limit_key)
        )
    ).scalars()
    return [PlanLimit(key=row.limit_key, max_value=row.max_value, unit=row.unit) for row in rows]


async def max_value_for_key(
    session: AsyncSession, studio_id: uuid.UUID, limit_key: str
) -> int | None:
    """The ceiling declared by the studio's plan for `limit_key`, or `None`
    when the plan does not declare it (or declares it unlimited)."""
    studio = await session.get(StudioModel, studio_id)
    if studio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "studio not found")
    plan = await resolve_plan(session, studio.plan)
    return cast(
        "int | None",
        await session.scalar(
            select(PlanLimitModel.max_value).where(
                PlanLimitModel.plan_code == plan.code,
                PlanLimitModel.limit_key == limit_key,
            )
        ),
    )


async def _measured_storage(
    session: AsyncSession, studio_id: uuid.UUID
) -> tuple[int, datetime | None]:
    """Latest `storage_bytes` measurement per project of the studio, summed.
    One project keeps its newest point only: an old point is history, not a
    second consumption."""
    latest = (
        select(InfraMeasurementModel.value, InfraMeasurementModel.measured_at)
        .join(ProjectModel, ProjectModel.id == InfraMeasurementModel.project_id)
        .where(
            InfraMeasurementModel.metric == MEASURED_STORAGE_METRIC,
            ProjectModel.studio_id == studio_id,
        )
        .distinct(InfraMeasurementModel.project_id)
        .order_by(
            InfraMeasurementModel.project_id,
            InfraMeasurementModel.measured_at.desc(),
        )
        .subquery()
    )
    total, measured_at = (
        await session.execute(
            select(func.coalesce(func.sum(latest.c.value), 0), func.max(latest.c.measured_at))
        )
    ).one()
    return int(total), cast("datetime | None", measured_at)


async def _live_storage(session: AsyncSession, studio_id: uuid.UUID) -> int:
    """Same definition as the collector and the transfer quota (non-deleted
    transfers), used only until the first measurement exists."""
    total = await session.scalar(
        select(func.coalesce(func.sum(TransferModel.size_bytes), 0)).where(
            TransferModel.studio_id == studio_id,
            TransferModel.status != "deleted",
        )
    )
    return int(total or 0)


async def _measured_sse(session: AsyncSession) -> tuple[int, datetime | None]:
    row = (
        await session.execute(
            select(InfraMeasurementModel.value, InfraMeasurementModel.measured_at)
            .where(InfraMeasurementModel.metric == MEASURED_SSE_METRIC)
            .order_by(InfraMeasurementModel.measured_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return event_stream.subscriber_count(), None
    return int(row[0]), cast("datetime", row[1])


async def _count(session: AsyncSession, model: type[Any], studio_id: uuid.UUID) -> int:
    column = model.studio_id
    total = await session.scalar(select(func.count()).select_from(model).where(column == studio_id))
    return int(total or 0)


async def _count_machines(session: AsyncSession, studio_id: uuid.UUID) -> int:
    """Machines owned by this studio's members. `machines.studio_id` is only
    the last selected studio (nullable), so it cannot define a tenant quota."""
    total = await session.scalar(
        select(func.count(func.distinct(MachineModel.id)))
        .join(StudioMembershipModel, StudioMembershipModel.user_id == MachineModel.owner_user_id)
        .where(StudioMembershipModel.studio_id == studio_id)
    )
    return int(total or 0)


def _counter_value(counters: list[StudioCounter], key: str) -> int:
    return next((counter.value for counter in counters if counter.key == key), 0)


async def refresh_counters(
    session: AsyncSession, studio_id: uuid.UUID, *, now: datetime | None = None
) -> list[StudioCounter]:
    """Recompute and cache the studio counters, then return them in display
    order. Storage and SSE come from the phase-M measurements; projects,
    members and machines are direct counts (a write path always needs them
    fresh). Caller decides when to commit."""
    measured_at = now or datetime.now(UTC)
    storage, storage_at = await _measured_storage(session, studio_id)
    storage_source: Literal["measured", "live"] = "measured"
    if storage_at is None:
        storage = await _live_storage(session, studio_id)
        storage_source = "live"
    sse, sse_at = await _measured_sse(session)
    sse_source: Literal["measured", "live"] = "measured" if sse_at is not None else "live"

    counters = [
        StudioCounter(
            key=STORAGE_BYTES,
            value=storage,
            source=storage_source,
            measured_at=storage_at or measured_at,
        ),
        StudioCounter(
            key=PROJECTS,
            value=await _count(session, ProjectModel, studio_id),
            source="live",
            measured_at=measured_at,
        ),
        StudioCounter(
            key=MEMBERS,
            value=await _count(session, StudioMembershipModel, studio_id),
            source="live",
            measured_at=measured_at,
        ),
        StudioCounter(
            key=MACHINES,
            value=await _count_machines(session, studio_id),
            source="live",
            measured_at=measured_at,
        ),
        StudioCounter(
            key=SSE_CONNECTIONS,
            value=sse,
            source=sse_source,
            measured_at=sse_at or measured_at,
        ),
    ]
    for counter in counters:
        statement = insert(StudioPlanCounterModel).values(
            studio_id=studio_id,
            limit_key=counter.key,
            value=counter.value,
            source=counter.source,
            measured_at=counter.measured_at,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    StudioPlanCounterModel.studio_id,
                    StudioPlanCounterModel.limit_key,
                ],
                set_={
                    "value": statement.excluded.value,
                    "source": statement.excluded.source,
                    "measured_at": statement.excluded.measured_at,
                },
            )
        )
    return counters


async def refresh_all_counters(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Refresh every studio's counters, e.g. right after one collector run so
    the cache follows the measurements it just wrote. Returns the studio count."""
    studio_ids = (await session.execute(select(StudioModel.id))).scalars().all()
    for studio_id in studio_ids:
        await refresh_counters(session, studio_id, now=now)
    return len(studio_ids)


async def studio_entitlements(
    session: AsyncSession, studio_id: uuid.UUID, *, now: datetime | None = None
) -> StudioEntitlements:
    """Plan, limits and counters of one studio: exactly what the Subscription
    and Usage screens display, nothing more."""
    studio = await session.get(StudioModel, studio_id)
    if studio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "studio not found")
    plan = await resolve_plan(session, studio.plan)
    return StudioEntitlements(
        studio_id=studio.id,
        plan=PlanSummary(code=plan.code, name=plan.name, rank=plan.plan_rank),
        limits=await limits_for_plan(session, plan.code),
        counters=await refresh_counters(session, studio_id, now=now),
        upgrade_url=upgrade_url(),
        generated_at=now or datetime.now(UTC),
    )


async def enforce_capacity(
    session: AsyncSession, studio_id: uuid.UUID, limit_key: str, requested: int
) -> None:
    """Refuse a write that would push a cumulative counter past its ceiling.
    The only place a `402 plan_limit_reached` is raised for a capacity limit."""
    maximum = await max_value_for_key(session, studio_id, limit_key)
    if maximum is None:
        return
    counters = await refresh_counters(session, studio_id)
    current = _counter_value(counters, limit_key)
    if current + requested > maximum:
        raise plan_limit_reached(limit_key, max_value=maximum, current=current, requested=requested)


async def enforce_studios_per_account(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Refuse a studio creation past the account's ceiling. The ceiling is the
    most generous one among the plans of the studios the account owns (the
    default plan when it owns none); the internal studio is not user-created
    and never counts."""
    owned_plans = list(
        (
            await session.execute(
                select(StudioModel.plan)
                .join(StudioMembershipModel, StudioMembershipModel.studio_id == StudioModel.id)
                .where(
                    StudioMembershipModel.user_id == user_id,
                    StudioMembershipModel.role == "owner",
                    StudioModel.is_internal.is_(False),
                )
            )
        ).scalars()
    )
    codes = {await resolve_plan_code(session, code) for code in owned_plans}
    codes.add(await default_plan_code(session))
    ceilings = [
        await session.scalar(
            select(PlanLimitModel.max_value).where(
                PlanLimitModel.plan_code == code,
                PlanLimitModel.limit_key == STUDIOS_PER_ACCOUNT,
            )
        )
        for code in codes
    ]
    if any(value is None for value in ceilings):
        return  # undeclared or unlimited on at least one plan
    maximum = max(cast("list[int]", ceilings))
    if len(owned_plans) + 1 > maximum:
        raise plan_limit_reached(
            STUDIOS_PER_ACCOUNT, max_value=maximum, current=len(owned_plans), requested=1
        )


async def resolve_plan_code(session: AsyncSession, code: str | None) -> str:
    return (await resolve_plan(session, code)).code


async def enforce_per_item(
    session: AsyncSession, studio_id: uuid.UUID, limit_key: str, requested: int
) -> None:
    """Refuse one item larger than a per-item ceiling (file size, per-note
    versions). The cumulative counter is not involved."""
    maximum = await max_value_for_key(session, studio_id, limit_key)
    if maximum is None:
        return
    if requested > maximum:
        raise plan_limit_reached(limit_key, max_value=maximum, current=0, requested=requested)


def reset_request_windows() -> None:
    """Drop the in-memory request windows (tests, process restart)."""
    _request_windows.clear()


async def enforce_request_rate(session: AsyncSession, studio_id: uuid.UUID) -> None:
    """Refuse a write that would exceed the plan's requests-per-minute ceiling.

    Only *successful* writes are counted (`record_request_rate`), so a `401`/
    `403` or another limit refusal never consumes a slot: the fail-closed
    authorization matrix keeps its canonical answers.

    shortcut: mono-instance — a bounded sliding window in this process, keyed
    by studio. A multi-replica deployment needs a shared store; the ceiling
    itself always comes from `plan_limits` through this module.
    """
    maximum = await max_value_for_key(session, studio_id, REQUESTS_PER_MINUTE)
    if maximum is None:
        return
    now = time.monotonic()
    window = _request_windows.setdefault(studio_id, deque())
    while window and now - window[0] >= _REQUEST_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= maximum:
        raise plan_limit_reached(
            REQUESTS_PER_MINUTE, max_value=maximum, current=len(window), requested=1
        )


def record_request_rate(studio_id: uuid.UUID) -> None:
    """Count one completed write in the studio's sliding minute window."""
    now = time.monotonic()
    window = _request_windows.setdefault(studio_id, deque())
    while window and now - window[0] >= _REQUEST_WINDOW_SECONDS:
        window.popleft()
    window.append(now)
    if len(_request_windows) > _REQUEST_WINDOW_MAX_STUDIOS:
        _request_windows.pop(next(iter(_request_windows)))
