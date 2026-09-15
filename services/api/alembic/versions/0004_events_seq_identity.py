"""Events realtime cursor: add `seq` identity column (roadmap step 4.1, DEC-0018).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN seq BIGINT GENERATED ALWAYS AS IDENTITY")
    op.execute("ALTER TABLE events ADD CONSTRAINT events_seq_key UNIQUE (seq)")


def downgrade() -> None:
    op.execute("ALTER TABLE events DROP CONSTRAINT events_seq_key")
    op.execute("ALTER TABLE events DROP COLUMN seq")
