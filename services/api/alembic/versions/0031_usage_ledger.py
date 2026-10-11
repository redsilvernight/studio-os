"""usage ledger: measured consumption per machine and collector event (DEC-0197)

Revision ID: 0031
Revises: 0029
Create Date: 2026-10-11

Additive: one new table, nothing existing is altered (AIWork and TaskLaunch are
untouched). Another branch also adds a revision after 0029; whoever lands second
re-chains `down_revision` onto the other one at integration.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: str | None = "0029"

TABLE = "usage_ledger_entries"


def _measurement_check(column: str, coverage: str) -> str:
    return (
        f"({column} IS NULL AND {coverage} = 'unknown')"
        f" OR ({column} IS NOT NULL AND {column} >= 0"
        f" AND {coverage} IN ('measured', 'estimated'))"
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id"),
            nullable=False,
        ),
        sa.Column(
            "task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "task_launch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_launches.id"),
            nullable=True,
        ),
        sa.Column(
            "ai_work_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_work_logs.id"),
            nullable=True,
        ),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("collector", sa.String(64), nullable=False),
        sa.Column("collector_version", sa.String(64), nullable=True),
        sa.Column("harness", sa.String(64), nullable=True),
        sa.Column("harness_version", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tokens_in", sa.BigInteger(), nullable=True),
        sa.Column("tokens_in_coverage", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("tokens_out", sa.BigInteger(), nullable=True),
        sa.Column("tokens_out_coverage", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("tokens_cached", sa.BigInteger(), nullable=True),
        sa.Column(
            "tokens_cached_coverage", sa.String(16), nullable=False, server_default="unknown"
        ),
        sa.Column(
            "cached_tokens_scope",
            sa.String(32),
            nullable=False,
            server_default="included_in_input",
        ),
        sa.Column("cost", sa.Numeric(18, 8), nullable=True),
        sa.Column("cost_coverage", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("cost_currency", sa.String(3), nullable=True),
        sa.Column("duration_seconds", sa.Numeric(14, 3), nullable=True),
        sa.Column("duration_coverage", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("price_list_id", sa.String(64), nullable=True),
        sa.Column("price_effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("machine_id", "source_event_id", name="uq_usage_ledger_machine_source"),
        sa.CheckConstraint(
            _measurement_check("tokens_in", "tokens_in_coverage"), name="ck_usage_ledger_tokens_in"
        ),
        sa.CheckConstraint(
            _measurement_check("tokens_out", "tokens_out_coverage"),
            name="ck_usage_ledger_tokens_out",
        ),
        sa.CheckConstraint(
            _measurement_check("tokens_cached", "tokens_cached_coverage"),
            name="ck_usage_ledger_tokens_cached",
        ),
        sa.CheckConstraint(
            _measurement_check("duration_seconds", "duration_coverage"),
            name="ck_usage_ledger_duration",
        ),
        sa.CheckConstraint(
            "cached_tokens_scope IN ('included_in_input', 'additional_to_input')",
            name="ck_usage_ledger_cached_scope",
        ),
        sa.CheckConstraint(
            "cached_tokens_scope <> 'included_in_input' OR tokens_cached IS NULL"
            " OR tokens_in IS NULL OR tokens_cached <= tokens_in",
            name="ck_usage_ledger_cached_within_input",
        ),
        sa.CheckConstraint(
            "(cost IS NULL AND cost_coverage = 'unknown' AND cost_currency IS NULL)"
            " OR (cost IS NOT NULL AND cost >= 0"
            " AND cost_coverage IN ('measured', 'estimated')"
            " AND cost_currency IS NOT NULL AND cost_currency ~ '^[A-Z]{3}$')",
            name="ck_usage_ledger_cost",
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_usage_ledger_period"),
        sa.CheckConstraint(
            "(price_list_id IS NULL) = (price_effective_from IS NULL)"
            " AND (cost IS NOT NULL OR price_list_id IS NULL)"
            " AND (cost_coverage <> 'estimated' OR price_list_id IS NOT NULL)",
            name="ck_usage_ledger_cost_pricing",
        ),
    )
    op.create_index("ix_usage_ledger_project_period", TABLE, ["project_id", "period_start"])
    op.create_index("ix_usage_ledger_session", TABLE, ["session_id"])
    op.create_index("ix_usage_ledger_task_launch", TABLE, ["task_launch_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_ledger_task_launch", table_name=TABLE)
    op.drop_index("ix_usage_ledger_session", table_name=TABLE)
    op.drop_index("ix_usage_ledger_project_period", table_name=TABLE)
    op.drop_table(TABLE)
