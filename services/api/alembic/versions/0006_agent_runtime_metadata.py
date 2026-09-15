"""Add Agent/AIWorkLog additive runtime observability metadata (UC-5).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLES = ("agents", "ai_work_logs")
_COLUMNS = ("agent_profile", "harness", "provider", "model")


def upgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.add_column(table, sa.Column(column, sa.String(), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        for column in reversed(_COLUMNS):
            op.drop_column(table, column)
