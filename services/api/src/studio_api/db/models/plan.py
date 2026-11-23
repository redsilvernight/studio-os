"""Plans, declarative limits and per-studio counters (S3-droits-plans).

`plans` is the catalogue. `plan_limits` holds one row per `(plan, limit_key)`;
`max_value = NULL` means explicitly unlimited. `studio_plan_counters` caches the
consumption derived from the phase-M `infra_measurements` rows so a limit check
never rescans the raw measurement history: it is derived data, deleting a row
only costs one refresh. No content (title, file name, body) is ever stored here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin


class PlanModel(TimestampMixin, Base):
    """One plan of the catalogue (`free`, `pro`). `is_default` marks the single
    plan a studio falls back to when its stored code is unknown."""

    __tablename__ = "plans"
    __table_args__ = (
        sa.CheckConstraint("plan_rank >= 0", name="ck_plans_plan_rank"),
        sa.Index(
            "uq_plans_one_default",
            "is_default",
            unique=True,
            postgresql_where=sa.text("is_default"),
        ),
    )

    code: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(100))
    plan_rank: Mapped[int] = mapped_column(default=0, server_default="0")
    is_default: Mapped[bool] = mapped_column(default=False, server_default=sa.false())


class PlanLimitModel(Base):
    """One declared ceiling of one plan. A missing `(plan, key)` row means the
    plan says nothing about that limit; `max_value IS NULL` means unlimited."""

    __tablename__ = "plan_limits"
    __table_args__ = (
        sa.CheckConstraint("max_value IS NULL OR max_value >= 0", name="ck_plan_limits_max_value"),
    )

    plan_code: Mapped[str] = mapped_column(
        sa.String(32),
        ForeignKey("plans.code", ondelete="CASCADE"),
        primary_key=True,
    )
    limit_key: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    max_value: Mapped[int | None] = mapped_column(BigInteger(), default=None)
    unit: Mapped[str] = mapped_column(sa.String(16), default="", server_default="")


class StudioPlanCounterModel(Base):
    """Cached consumption of one limit for one studio. `source` records where
    the value came from (`measured` from `infra_measurements`, `live` from a
    direct count); `measured_at` is the time of the underlying measurement."""

    __tablename__ = "studio_plan_counters"
    __table_args__ = (sa.CheckConstraint("value >= 0", name="ck_studio_plan_counters_value"),)

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="CASCADE"),
        primary_key=True,
    )
    limit_key: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger(), default=0, server_default="0")
    source: Mapped[str] = mapped_column(sa.String(32), default="live", server_default="live")
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
