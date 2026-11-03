"""Task launch production approval (DEC-0235).

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"


def upgrade() -> None:
    op.add_column(
        "task_launches",
        sa.Column("allow_production", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("task_launches", "allow_production")
