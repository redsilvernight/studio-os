"""Infrastructure cost measurements (phase M): `infra_measurements`.

Additive and reversible: one table, one nullable project FK (`CASCADE`), one
index on (metric, measured_at). No backfill, no row rewrite. Downgrade drops
the table.

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "infra_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(128), server_default="", nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column(
            "measured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_infra_measurements_metric_measured_at", "infra_measurements", ["metric", "measured_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_infra_measurements_metric_measured_at", table_name="infra_measurements")
    op.drop_table("infra_measurements")
