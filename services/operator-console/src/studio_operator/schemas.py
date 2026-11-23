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


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=6, max_length=8)


class EnrollmentRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class EnrollmentStart(BaseModel):
    otpauth_uri: str
    secret: str
    qr_svg: str
    expires_in: int


class EnrollmentConfirm(BaseModel):
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
    suspension_reason: str | None = None
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
    """Motif obligatoire, visible du client (fiche C2). Stored in
    `studios.suspension_reason` (migration 0053) and exposed to the studio's
    own members by `GET /api/v1/studio`; cleared when the suspension is lifted."""

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
    api_latency_p50_ms: int | None = None
    unpaid_in_grace: int | None = None
    services: list[ServiceHealth]
    alerts: list[Alert]
    has_measures: bool


class UsageReport(BaseModel):
    window_days: int
    generated_at: datetime
    studios: int
    storage: StorageUsage
    api_calls: int | None = None
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
    suspension_reason: str | None = None
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


BreakGlassScope = Literal["metadata", "support"]
BreakGlassStatus = Literal["requested", "approved", "denied", "expired", "revoked"]


class BreakGlassRequest(BaseModel):
    """One request in the C5 queue: who asked, why, the declared scope and the
    owner's decision. Never a content excerpt."""

    id: uuid.UUID
    studio_id: uuid.UUID
    studio_name: str | None = None
    operator_ref: str
    reason: str
    scope: BreakGlassScope
    status: BreakGlassStatus
    requested_at: datetime
    decided_at: datetime | None = None
    expires_at: datetime | None = None


class BreakGlassQueue(BaseModel):
    total: int
    requests: list[BreakGlassRequest]


class BreakGlassCreateRequest(BaseModel):
    studio_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=2000)
    scope: BreakGlassScope = "metadata"

    def stripped_reason(self) -> str:
        return self.reason.strip()
