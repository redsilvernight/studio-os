"""Response and request shapes of the operator console.

Aggregates only: identity, plan, status, sizes, counts and measured totals.
No project name, file name, note body or any other client content is ever
part of these models. Money is formatted server-side (`"12.34"`) so every
console renders the same rounding; percentages carry one decimal.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ServiceState = Literal["ok", "degraded", "unavailable"]


class OperatorProfile(BaseModel):
    email: str
    display_name: str


class OperatorSession(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    operator: OperatorProfile


class MfaRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=6, max_length=8)


class StorageUsage(BaseModel):
    used_bytes: int
    quota_bytes: int | None = None
    percent: float | None = None


class StudioSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    status: str
    created_at: datetime
    owner_email: str | None = None
    storage: StorageUsage
    members: int
    members_limit: int | None = None


class StudioList(BaseModel):
    total: int
    studios: list[StudioSummary]


class CostTotal(BaseModel):
    currency: str
    amount: str


class UsageTotals(BaseModel):
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_seconds: float | None = None
    costs: list[CostTotal] = Field(default_factory=list)


class StudioUsageRow(BaseModel):
    id: uuid.UUID
    name: str
    plan: str
    status: str
    storage: StorageUsage
    members: int
    members_limit: int | None = None
    usage: UsageTotals


class StudioDetail(BaseModel):
    studio: StudioSummary
    usage_window_days: int
    usage: UsageTotals


class SuspensionRequest(BaseModel):
    """Motif obligatoire. It is not persisted yet (no column): see the
    console README — only `studios.status` is written, the motif goes to the
    operator log until the dedicated migration lands."""

    reason: str = Field(min_length=3, max_length=500)


class ServiceHealth(BaseModel):
    key: Literal["api", "database", "stripe_webhooks"]
    label: str
    state: ServiceState
    detail: str
    measured_at: datetime | None = None


class Alert(BaseModel):
    level: Literal["warning", "critical"]
    title: str
    detail: str


class Dashboard(BaseModel):
    generated_at: datetime
    active_studios: int
    new_studios_7d: int
    storage: StorageUsage
    error_rate_5xx_24h: float | None = None
    unpaid_in_grace: int | None = None
    services: list[ServiceHealth]
    alerts: list[Alert]
    has_measures: bool


class UsageReport(BaseModel):
    window_days: int
    generated_at: datetime
    studios: int
    storage: StorageUsage
    totals: UsageTotals
    top_studios: list[StudioUsageRow]
    over_quota: list[StudioUsageRow]
    has_measures: bool


class SuspendedStudio(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    members: int
    storage: StorageUsage
    owner_email: str | None = None
    since: datetime | None = None


class SuspensionList(BaseModel):
    total: int
    studios: list[SuspendedStudio]


class FeatureAvailability(BaseModel):
    """An operator view whose source is not deployed yet (S4-Stripe for
    billing, the break-glass service for C5)."""

    available: bool
    reason_code: str
    message: str
