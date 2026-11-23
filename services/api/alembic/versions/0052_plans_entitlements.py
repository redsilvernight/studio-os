"""Plans, declarative limits and per-studio counters (S3-droits-plans).

Three additive tables and one foreign key. Values come from the validated
decisions DEC-0401 (plan catalogue) and DEC-0402 (limits); DEC-0387 is
superseded. The code never hard-codes a number: it reads these rows.

- `plans` is the catalogue (`free`, `pro`). `is_default` marks the single plan
  a studio falls back to when its `studios.plan` code is unknown.
- `plan_limits` declares one row per `(plan, limit_key)`. `max_value` is the
  ceiling; `NULL` means explicitly unlimited.
- `studio_plan_counters` caches the per-studio consumption measured by the
  phase-M collector (`infra_measurements`), so a limit check never rescans the
  raw measurement history. The counter is derived data: deleting a row only
  costs one refresh.

`studios.plan` gains a `RESTRICT` foreign key so a plan still used by a studio
cannot be removed by accident. Both plan codes are seeded before the key is
added; every existing value (`free`) validates.

Downgrade drops the foreign key and the three tables; it never touches studio
or measurement rows.

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

GIB = 1024**3
MIB = 1024**2

PLAN_SEED: tuple[dict[str, Any], ...] = (
    {"code": "free", "name": "Gratuit", "plan_rank": 0, "is_default": True},
    {"code": "pro", "name": "Pro", "plan_rank": 10, "is_default": False},
)

# DEC-0401 / DEC-0402. `None` = explicitly unlimited. One row per
# (plan, limit_key). Prices and the monthly/annual split stay out of this table.
LIMIT_SEED: tuple[tuple[str, str, int | None, str], ...] = (
    # plan, limit key, max value, unit
    ("free", "storage_bytes", 2 * GIB, "bytes"),
    ("free", "file_size_bytes", 100 * MIB, "bytes"),
    ("free", "event_retention_days", 30, "days"),
    ("free", "timeline_retention_days", 30, "days"),
    ("free", "usage_retention_days", 30, "days"),
    ("free", "vault_versions_per_note", 10, "versions"),
    ("free", "transfer_retention_days", 14, "days"),
    ("free", "snapshot_retention_days", 14, "days"),
    ("free", "sse_connections", 5, "connections"),
    ("free", "on_demand_backups_per_day", 0, "backups"),
    ("free", "backup_daily_retention_days", 0, "days"),
    ("free", "requests_per_minute", 60, "requests"),
    ("free", "studios_per_account", 2, "studios"),
    ("free", "projects", 50, "projects"),
    ("free", "members", 10, "members"),
    ("free", "machines", 5, "machines"),
    ("pro", "storage_bytes", 25 * GIB, "bytes"),
    ("pro", "file_size_bytes", 5 * GIB, "bytes"),
    ("pro", "event_retention_days", 365, "days"),
    ("pro", "timeline_retention_days", 365, "days"),
    ("pro", "usage_retention_days", 365, "days"),
    ("pro", "vault_versions_per_note", 200, "versions"),
    ("pro", "transfer_retention_days", 90, "days"),
    ("pro", "snapshot_retention_days", 90, "days"),
    ("pro", "sse_connections", 50, "connections"),
    ("pro", "on_demand_backups_per_day", 1, "backups"),
    ("pro", "backup_daily_retention_days", 30, "days"),
    ("pro", "requests_per_minute", 600, "requests"),
    ("pro", "studios_per_account", 10, "studios"),
    ("pro", "projects", None, "projects"),
    ("pro", "members", 25, "members"),
    ("pro", "machines", None, "machines"),
)


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("plan_rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("plan_rank >= 0", name="ck_plans_plan_rank"),
    )
    op.create_index(
        "uq_plans_one_default",
        "plans",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.bulk_insert(
        sa.table(
            "plans",
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("plan_rank", sa.Integer),
            sa.column("is_default", sa.Boolean),
        ),
        list(PLAN_SEED),
    )

    op.create_table(
        "plan_limits",
        sa.Column(
            "plan_code",
            sa.String(32),
            sa.ForeignKey("plans.code", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("limit_key", sa.String(64), primary_key=True),
        sa.Column("max_value", sa.BigInteger(), nullable=True),
        sa.Column("unit", sa.String(16), nullable=False, server_default=""),
        sa.CheckConstraint("max_value IS NULL OR max_value >= 0", name="ck_plan_limits_max_value"),
    )
    op.bulk_insert(
        sa.table(
            "plan_limits",
            sa.column("plan_code", sa.String),
            sa.column("limit_key", sa.String),
            sa.column("max_value", sa.BigInteger),
            sa.column("unit", sa.String),
        ),
        [
            {"plan_code": plan, "limit_key": key, "max_value": value, "unit": unit}
            for plan, key, value, unit in LIMIT_SEED
        ],
    )

    op.create_table(
        "studio_plan_counters",
        sa.Column(
            "studio_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("limit_key", sa.String(64), primary_key=True),
        sa.Column("value", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(32), nullable=False, server_default="live"),
        sa.Column(
            "measured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("value >= 0", name="ck_studio_plan_counters_value"),
    )

    # Both plan codes are seeded above, so every existing studio (all `free`)
    # validates against the new key.
    op.create_foreign_key(
        "fk_studios_plan",
        "studios",
        "plans",
        ["plan"],
        ["code"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_studios_plan", "studios", type_="foreignkey")
    op.drop_table("studio_plan_counters")
    op.drop_table("plan_limits")
    op.drop_index("uq_plans_one_default", table_name="plans")
    op.drop_table("plans")
