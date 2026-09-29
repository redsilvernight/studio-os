"""L3 remediation (DEC-0163): index `ai_work_logs.session_id` and set the FK
`ondelete` to `SET NULL` so deleting a session never orphans or blocks the
linked work entries.

Reversible: downgrade drops the index and restores the FK without `ondelete`.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_ai_work_logs_session_id_work_sessions", "ai_work_logs", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_ai_work_logs_session_id_work_sessions",
        "ai_work_logs",
        "work_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_ai_work_logs_session_id", "ai_work_logs", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_work_logs_session_id", table_name="ai_work_logs")
    op.drop_constraint(
        "fk_ai_work_logs_session_id_work_sessions", "ai_work_logs", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_ai_work_logs_session_id_work_sessions",
        "ai_work_logs",
        "work_sessions",
        ["session_id"],
        ["id"],
    )
