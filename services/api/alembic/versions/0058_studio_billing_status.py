"""Stripe subscription status and trial end mirrored on studios (S4b).

`studios.billing_status` copies Stripe's subscription status and
`studios.billing_trial_ends_at` its `trial_end`, so the dashboard and the
operator console can show them. Both nullable and additive; written only by the
signed webhook.

Reversible: drop both columns.

Revision ID: 0058
Revises: 0057
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("studios", sa.Column("billing_status", sa.String(32), nullable=True))
    op.add_column(
        "studios", sa.Column("billing_trial_ends_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("studios", "billing_trial_ends_at")
    op.drop_column("studios", "billing_status")
