from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


def _measurement_check(column: str, coverage: str) -> str:
    return (
        f"({column} IS NULL AND {coverage} = 'unknown')"
        f" OR ({column} IS NOT NULL AND {column} >= 0"
        f" AND {coverage} IN ('measured', 'estimated'))"
    )


class UsageLedgerEntryModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """One measured fact about what a machine's agent run consumed (DEC-0197).

    Every measure column is nullable and paired with a mandatory coverage
    column: an unmeasured metric is NULL with coverage `unknown`, never 0, so
    "nothing happened" and "nobody measured" stay distinguishable at the SQL
    level. Cached tokens are stored apart from `tokens_in`, with the scope
    saying whether the collector already folded them in — never a double count.
    `(machine_id, source_event_id)` is the deduplication key of the ingestion.
    """

    __tablename__ = "usage_ledger_entries"
    __table_args__ = (
        UniqueConstraint("machine_id", "source_event_id", name="uq_usage_ledger_machine_source"),
        CheckConstraint(
            _measurement_check("tokens_in", "tokens_in_coverage"), name="ck_usage_ledger_tokens_in"
        ),
        CheckConstraint(
            _measurement_check("tokens_out", "tokens_out_coverage"),
            name="ck_usage_ledger_tokens_out",
        ),
        CheckConstraint(
            _measurement_check("tokens_cached", "tokens_cached_coverage"),
            name="ck_usage_ledger_tokens_cached",
        ),
        CheckConstraint(
            _measurement_check("duration_seconds", "duration_coverage"),
            name="ck_usage_ledger_duration",
        ),
        CheckConstraint(
            "cached_tokens_scope IN ('included_in_input', 'additional_to_input')",
            name="ck_usage_ledger_cached_scope",
        ),
        CheckConstraint(
            "cached_tokens_scope <> 'included_in_input' OR tokens_cached IS NULL"
            " OR tokens_in IS NULL OR tokens_cached <= tokens_in",
            name="ck_usage_ledger_cached_within_input",
        ),
        CheckConstraint(
            "(cost IS NULL AND cost_coverage = 'unknown' AND cost_currency IS NULL)"
            " OR (cost IS NOT NULL AND cost >= 0"
            " AND cost_coverage IN ('measured', 'estimated')"
            " AND cost_currency IS NOT NULL AND cost_currency ~ '^[A-Z]{3}$')",
            name="ck_usage_ledger_cost",
        ),
        CheckConstraint(
            "(cost IS NULL AND cost_basis IS NULL)"
            " OR (cost IS NOT NULL AND cost_basis IN ('measured_billed', 'api_equivalent'))",
            name="ck_usage_ledger_cost_basis",
        ),
        CheckConstraint("period_end >= period_start", name="ck_usage_ledger_period"),
        CheckConstraint(
            "(price_list_id IS NULL) = (price_effective_from IS NULL)"
            " AND (cost IS NOT NULL OR price_list_id IS NULL)"
            " AND (cost_coverage <> 'estimated' OR price_list_id IS NOT NULL)",
            name="ck_usage_ledger_cost_pricing",
        ),
        Index("ix_usage_ledger_project_period", "project_id", "period_start"),
        Index("ix_usage_ledger_session", "session_id"),
        Index("ix_usage_ledger_task_launch", "task_launch_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    machine_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("machines.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), default=None
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("work_sessions.id", ondelete="SET NULL"),
        default=None,
    )
    task_launch_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("task_launches.id"), default=None
    )
    ai_work_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_work_logs.id"), default=None
    )
    source_event_id: Mapped[str] = mapped_column(String(128))

    collector: Mapped[str] = mapped_column(String(64))
    collector_version: Mapped[str | None] = mapped_column(String(64), default=None)
    harness: Mapped[str | None] = mapped_column(String(64), default=None)
    harness_version: Mapped[str | None] = mapped_column(String(64), default=None)
    provider: Mapped[str | None] = mapped_column(String(64), default=None)
    model: Mapped[str | None] = mapped_column(String(128), default=None)

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    tokens_in: Mapped[int | None] = mapped_column(BigInteger, default=None)
    tokens_in_coverage: Mapped[str] = mapped_column(String(16), default="unknown")
    tokens_out: Mapped[int | None] = mapped_column(BigInteger, default=None)
    tokens_out_coverage: Mapped[str] = mapped_column(String(16), default="unknown")
    tokens_cached: Mapped[int | None] = mapped_column(BigInteger, default=None)
    tokens_cached_coverage: Mapped[str] = mapped_column(String(16), default="unknown")
    cached_tokens_scope: Mapped[str] = mapped_column(String(32), default="included_in_input")

    cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), default=None)
    cost_coverage: Mapped[str] = mapped_column(String(16), default="unknown")
    cost_currency: Mapped[str | None] = mapped_column(String(3), default=None)
    cost_basis: Mapped[str | None] = mapped_column(String(32), default=None)

    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), default=None)
    duration_coverage: Mapped[str] = mapped_column(String(16), default="unknown")

    price_list_id: Mapped[str | None] = mapped_column(String(64), default=None)
    price_effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class UsageSubscriptionModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """A flat-rate plan a project pays (DEC-0361). Its monthly price is spread
    over the covered ledger entries at read time; no share is ever stored."""

    __tablename__ = "usage_subscriptions"
    __table_args__ = (
        CheckConstraint("monthly_price >= 0", name="ck_usage_subscription_price"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_usage_subscription_currency"),
        CheckConstraint(
            "cardinality(harnesses) > 0 OR cardinality(providers) > 0",
            name="ck_usage_subscription_coverage",
        ),
        CheckConstraint(
            "ends_on IS NULL OR ends_on >= starts_on", name="ck_usage_subscription_period"
        ),
        Index("ix_usage_subscriptions_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    label: Mapped[str] = mapped_column(String(120))
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    harnesses: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    providers: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date, default=None)


class UsagePriceListModel(UUIDPKMixin, Base):
    """An immutable, dated price grid served to every daemon (DEC-0362).
    `project_id` NULL is the global grid. `price_list_id` is unique
    server-wide: it is the reference a priced ledger entry keeps."""

    __tablename__ = "usage_price_lists"
    __table_args__ = (
        UniqueConstraint("price_list_id", name="uq_usage_price_lists_price_list_id"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_usage_price_list_currency"),
        Index("ix_usage_price_lists_scope", "project_id", "effective_from"),
    )

    price_list_id: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), default=None
    )
    currency: Mapped[str] = mapped_column(String(3))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    models: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
