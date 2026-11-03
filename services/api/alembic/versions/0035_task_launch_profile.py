"""task launch work profile: the pin a profiled launch was admitted against

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-15

Additive: three nullable columns, no backfill, no rewrite of existing rows.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"


def upgrade() -> None:
    op.add_column("task_launches", sa.Column("profile_key", sa.String(64), nullable=True))
    op.add_column(
        "task_launches",
        sa.Column("profile_contract_version", sa.Integer(), nullable=True),
    )
    op.add_column("task_launches", sa.Column("profile_digest", sa.String(71), nullable=True))


def downgrade() -> None:
    op.drop_column("task_launches", "profile_digest")
    op.drop_column("task_launches", "profile_contract_version")
    op.drop_column("task_launches", "profile_key")
