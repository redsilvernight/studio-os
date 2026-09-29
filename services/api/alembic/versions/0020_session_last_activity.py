"""Session presence (C1, DEC-0157): additive `last_activity_at` on
work_sessions, backfilled from `started_at` — the read-side presence
(status/expiry derived at read, never stored) of live work sessions.
No heartbeat, no session closing here (effective closing is L2).

Purely additive and reversible: downgrade drops the column.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_sessions", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE work_sessions SET last_activity_at = started_at")


def downgrade() -> None:
    op.drop_column("work_sessions", "last_activity_at")
