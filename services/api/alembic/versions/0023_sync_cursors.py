"""sync cursors: per-session sync cursor and per-task handoff cursor

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"


def upgrade() -> None:
    op.add_column("work_sessions", sa.Column("sync_cursor_seq", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("handoff_cursor_seq", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "handoff_cursor_seq")
    op.drop_column("work_sessions", "sync_cursor_seq")
