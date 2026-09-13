"""Add Transfer.content_md5 (DEC-0025 — server-verified upload integrity).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transfers", sa.Column("content_md5", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("transfers", "content_md5")
