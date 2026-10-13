"""launch budgets: explicit project policy and per-launch reservations

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-13

Additive: two new tables, nothing existing is altered. The policy row is the
per-project admission lock; a reservation is unique per launch.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | None = "0032"

POLICIES = "budget_policies"
RESERVATIONS = "budget_reservations"


def upgrade() -> None:
    op.create_table(
        POLICIES,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cost_limit", sa.Numeric(18, 8), nullable=True),
        sa.Column("token_limit", sa.BigInteger(), nullable=True),
        sa.Column("max_active_launches", sa.Integer(), nullable=True),
        sa.Column("reservation_cost", sa.Numeric(18, 8), nullable=True),
        sa.Column("reservation_tokens", sa.BigInteger(), nullable=True),
        sa.Column("unknown_cost", sa.String(32), nullable=False),
        sa.Column("late_usage", sa.String(32), nullable=False),
        sa.Column("settle_after_seconds", sa.Integer(), nullable=False),
        sa.Column("alert_thresholds", postgresql.JSONB(), nullable=False),
        sa.Column(
            "proposed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "approved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", name="uq_budget_policies_project"),
        sa.CheckConstraint("mode IN ('alert_only', 'enforce')", name="ck_budget_policies_mode"),
        sa.CheckConstraint(
            "period IN ('day', 'month', 'lifetime')", name="ck_budget_policies_period"
        ),
        sa.CheckConstraint(
            "unknown_cost IN ('charge_reservation', 'ignore')",
            name="ck_budget_policies_unknown_cost",
        ),
        sa.CheckConstraint(
            "late_usage IN ('hold_reservation', 'release')", name="ck_budget_policies_late_usage"
        ),
        sa.CheckConstraint(
            "(approved_at IS NULL) = (approved_by_user_id IS NULL)",
            name="ck_budget_policies_approval",
        ),
        sa.CheckConstraint(
            "max_active_launches IS NULL OR max_active_launches >= 1",
            name="ck_budget_policies_slots",
        ),
    )
    op.create_table(
        RESERVATIONS,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budget_policies.id"),
            nullable=False,
        ),
        sa.Column(
            "task_launch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_launches.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reserved_cost", sa.Numeric(18, 8), nullable=True),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=True),
        sa.Column("settle_basis", sa.String(16), nullable=True),
        sa.Column("alerts", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("task_launch_id", name="uq_budget_reservations_launch"),
        sa.CheckConstraint(
            "status IN ('held', 'settled', 'released')", name="ck_budget_reservations_status"
        ),
        sa.CheckConstraint(
            "settle_basis IS NULL OR settle_basis IN ('measured', 'reservation', 'none')",
            name="ck_budget_reservations_basis",
        ),
        sa.CheckConstraint(
            "(status = 'held') = (settled_at IS NULL)", name="ck_budget_reservations_settled"
        ),
    )
    op.create_index("ix_budget_reservations_project", RESERVATIONS, ["project_id", "created_at"])
    op.create_index("ix_budget_reservations_held", RESERVATIONS, ["project_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_budget_reservations_held", table_name=RESERVATIONS)
    op.drop_index("ix_budget_reservations_project", table_name=RESERVATIONS)
    op.drop_table(RESERVATIONS)
    op.drop_table(POLICIES)
