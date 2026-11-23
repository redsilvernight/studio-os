"""Announced retention purge (0054).

Two additive tables, dropped by `downgrade()`:

- `retention_purge_notices`: one announcement per `(studio, kind)` while it is
  open (`purged_at IS NULL`, enforced unique by a partial index). `cutoff` is
  fixed at announcement time; `purge_after` is the earliest purge date.
- `retention_purge_log`: one audit row per executed purge, counts only — never
  a title, a note body or a file name.

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

KIND_CHECK = "kind IN ('events', 'timeline', 'usage', 'transfers', 'snapshots')"


def upgrade() -> None:
    op.create_table(
        "retention_purge_notices",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "studio_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exported_hint", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint(KIND_CHECK, name="ck_retention_purge_notices_kind"),
        sa.CheckConstraint("purge_after > announced_at", name="ck_retention_purge_notices_window"),
    )
    op.create_index(
        "ix_retention_purge_notices_studio_id",
        "retention_purge_notices",
        ["studio_id"],
    )
    op.create_index(
        "uq_retention_purge_notices_open",
        "retention_purge_notices",
        ["studio_id", "kind"],
        unique=True,
        postgresql_where=sa.text("purged_at IS NULL"),
    )
    op.create_index(
        "ix_retention_purge_notices_due",
        "retention_purge_notices",
        ["purge_after"],
        postgresql_where=sa.text("purged_at IS NULL"),
    )

    op.create_table(
        "retention_purge_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "studio_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("rows_deleted", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("objects_deleted", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(KIND_CHECK, name="ck_retention_purge_log_kind"),
        sa.CheckConstraint("rows_deleted >= 0", name="ck_retention_purge_log_rows"),
        sa.CheckConstraint("objects_deleted >= 0", name="ck_retention_purge_log_objects"),
    )
    op.create_index(
        "ix_retention_purge_log_studio_id",
        "retention_purge_log",
        ["studio_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_retention_purge_log_studio_id", table_name="retention_purge_log")
    op.drop_table("retention_purge_log")
    op.drop_index("ix_retention_purge_notices_due", table_name="retention_purge_notices")
    op.drop_index("uq_retention_purge_notices_open", table_name="retention_purge_notices")
    op.drop_index("ix_retention_purge_notices_studio_id", table_name="retention_purge_notices")
    op.drop_table("retention_purge_notices")
