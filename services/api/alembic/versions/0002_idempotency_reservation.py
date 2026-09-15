"""Idempotency reservation: pending/completed status, nullable response.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "idempotency_keys",
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
    )
    op.alter_column(
        "idempotency_keys", "response_status", existing_type=sa.Integer(), nullable=True
    )
    op.alter_column(
        "idempotency_keys",
        "response_body",
        existing_type=postgresql.JSONB(),
        nullable=True,
    )


def downgrade() -> None:
    # A row can be `status=pending` with no response yet (a reservation whose
    # creation is still running or was abandoned by a crashed request — see
    # DEC-0015). It has no response to preserve, and `response_status`/
    # `response_body` cannot become NOT NULL again while such a row exists —
    # drop only those incomplete reservations, never a completed response.
    op.execute("DELETE FROM idempotency_keys WHERE status = 'pending'")
    op.alter_column(
        "idempotency_keys",
        "response_body",
        existing_type=postgresql.JSONB(),
        nullable=False,
    )
    op.alter_column(
        "idempotency_keys", "response_status", existing_type=sa.Integer(), nullable=False
    )
    op.drop_column("idempotency_keys", "status")
