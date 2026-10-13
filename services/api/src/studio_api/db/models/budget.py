from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class BudgetPolicyModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """The explicit budget of one project. Its row is the admission lock:
    every admission of the project takes it `FOR UPDATE` before reserving."""

    __tablename__ = "budget_policies"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_budget_policies_project"),
        CheckConstraint("mode IN ('alert_only', 'enforce')", name="ck_budget_policies_mode"),
        CheckConstraint("period IN ('day', 'month', 'lifetime')", name="ck_budget_policies_period"),
        CheckConstraint(
            "unknown_cost IN ('charge_reservation', 'ignore')",
            name="ck_budget_policies_unknown_cost",
        ),
        CheckConstraint(
            "late_usage IN ('hold_reservation', 'release')", name="ck_budget_policies_late_usage"
        ),
        CheckConstraint(
            "(approved_at IS NULL) = (approved_by_user_id IS NULL)",
            name="ck_budget_policies_approval",
        ),
        CheckConstraint(
            "max_active_launches IS NULL OR max_active_launches >= 1",
            name="ck_budget_policies_slots",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    mode: Mapped[str] = mapped_column(String(16), server_default="alert_only")
    period: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    cost_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), default=None)
    token_limit: Mapped[int | None] = mapped_column(BigInteger, default=None)
    max_active_launches: Mapped[int | None] = mapped_column(Integer, default=None)
    reservation_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), default=None)
    reservation_tokens: Mapped[int | None] = mapped_column(BigInteger, default=None)
    unknown_cost: Mapped[str] = mapped_column(String(32))
    late_usage: Mapped[str] = mapped_column(String(32))
    settle_after_seconds: Mapped[int] = mapped_column(Integer)
    alert_thresholds: Mapped[list[int]] = mapped_column(JSONB)
    proposed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), default=None
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), default=None
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class BudgetReservationModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """What one admitted launch holds against its project's budget. Unique per
    launch: an admission replayed or raced never holds twice."""

    __tablename__ = "budget_reservations"
    __table_args__ = (
        UniqueConstraint("task_launch_id", name="uq_budget_reservations_launch"),
        CheckConstraint(
            "status IN ('held', 'settled', 'released')", name="ck_budget_reservations_status"
        ),
        CheckConstraint(
            "settle_basis IS NULL OR settle_basis IN ('measured', 'reservation', 'none')",
            name="ck_budget_reservations_basis",
        ),
        CheckConstraint(
            "(status = 'held') = (settled_at IS NULL)", name="ck_budget_reservations_settled"
        ),
        Index("ix_budget_reservations_project", "project_id", "created_at"),
        Index("ix_budget_reservations_held", "project_id", "status"),
        Index("ix_budget_reservations_policy", "policy_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    policy_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("budget_policies.id")
    )
    task_launch_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("task_launches.id")
    )
    status: Mapped[str] = mapped_column(String(16), default="held")
    reserved_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), default=None)
    reserved_tokens: Mapped[int | None] = mapped_column(BigInteger, default=None)
    settle_basis: Mapped[str | None] = mapped_column(String(16), default=None)
    alerts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
