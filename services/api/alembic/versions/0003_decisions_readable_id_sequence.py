"""Decisions readable_id: Postgres sequence instead of COUNT(*) (roadmap step 2).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE decisions_readable_id_seq")
    op.execute(
        "SELECT setval('decisions_readable_id_seq', "
        "COALESCE((SELECT MAX(CAST(SUBSTRING(readable_id FROM 5) AS INTEGER)) "
        "FROM decisions), 0) + 1, false)"
    )


def downgrade() -> None:
    op.execute("DROP SEQUENCE decisions_readable_id_seq")
