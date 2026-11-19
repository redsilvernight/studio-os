"""Per-machine active studio: `machines.studio_id`.

Optional on purpose: a machine that never selected a studio keeps `NULL` and
the active studio is resolved from the user's memberships. `ON DELETE
RESTRICT`, like every other `studio_id`: a studio that still scopes machines
is never deleted implicitly.

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "machines",
        sa.Column(
            "studio_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_machines_studio_id", "machines", ["studio_id"])


def downgrade() -> None:
    op.drop_index("ix_machines_studio_id", table_name="machines")
    op.drop_column("machines", "studio_id")
