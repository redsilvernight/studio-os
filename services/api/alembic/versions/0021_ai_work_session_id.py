"""L3 handoff: add `session_id` to `ai_work_logs` for traceability.

Additive, nullable FK to `work_sessions.id`. Downgrade drops the column
and FK.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_work_logs", sa.Column("session_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_ai_work_logs_session_id_work_sessions",
        "ai_work_logs",
        "work_sessions",
        ["session_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ai_work_logs_session_id_work_sessions", "ai_work_logs", type_="foreignkey"
    )
    op.drop_column("ai_work_logs", "session_id")
