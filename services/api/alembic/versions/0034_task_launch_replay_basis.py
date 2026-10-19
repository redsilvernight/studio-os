"""task launch replay basis: accepted replay preview on the attempt it created

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-14

Additive: one nullable JSONB column, no backfill, no rewrite of existing rows.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"


def upgrade() -> None:
    op.add_column(
        "task_launches",
        sa.Column("replay_basis", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_launches", "replay_basis")
