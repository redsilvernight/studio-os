"""Stripe webhook events and unpaid grace marker (S4-stripe).

`stripe_events` records each applied event id (replay = no effect).
`studios.billing_past_due_since` marks the start of the unpaid grace delay;
NULL while the subscription is paid. Both additive; no data is ever deleted by
the downgrade this supports.

Reversible: drop the column then the table.

Revision ID: 0057
Revises: 0056
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        "studios", sa.Column("billing_past_due_since", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("studios", "billing_past_due_since")
    op.drop_table("stripe_events")
