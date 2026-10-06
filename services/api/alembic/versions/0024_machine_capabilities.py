"""machine capabilities: latest reported launch aptitude per machine

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"


def upgrade() -> None:
    op.add_column("machines", sa.Column("capabilities", postgresql.JSONB(), nullable=True))
    op.add_column(
        "machines",
        sa.Column("capabilities_reported_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("machines", "capabilities_reported_at")
    op.drop_column("machines", "capabilities")
