"""Studio export and deletion (lot « export complet et suppression »).

Additive and reversible:

- `studios.deletion_requested_at` / `studios.deletion_scheduled_at`: the grace
  window of a deletion request (both NULL while the studio is not scheduled).
  A studio whose `deletion_scheduled_at` is set is read-only until the request
  is cancelled or `purge_due_studios` runs past that date.
- `studio_exports`: one archive per export request, stored in object storage
  under `object_key`, readable through a short presigned URL until `expires_at`.

`requested_by_user_id` is `ON DELETE SET NULL`: deleting the requester's
account must never erase the audit trail of an export. `studio_id` is
`ON DELETE CASCADE`: an export never outlives the studio it belongs to.

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "studios",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "studios",
        sa.Column("deletion_scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The purge worker scans scheduled studios only; a partial index keeps the
    # scheduled set cheap on an instance with many active studios.
    op.create_index(
        "ix_studios_deletion_scheduled_at",
        "studios",
        ["deletion_scheduled_at"],
        postgresql_where=sa.text("deletion_scheduled_at IS NOT NULL"),
    )

    op.create_table(
        "studio_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "studio_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_studio_exports_studio_id", "studio_exports", ["studio_id"])


def downgrade() -> None:
    op.drop_index("ix_studio_exports_studio_id", table_name="studio_exports")
    op.drop_table("studio_exports")
    op.drop_index("ix_studios_deletion_scheduled_at", table_name="studios")
    op.drop_column("studios", "deletion_scheduled_at")
    op.drop_column("studios", "deletion_requested_at")
