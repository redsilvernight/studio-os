from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
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

    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), default=None)
    duration_coverage: Mapped[str] = mapped_column(String(16), default="unknown")

    price_list_id: Mapped[str | None] = mapped_column(String(64), default=None)
    price_effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
