"""Stripe customer of a studio (S4-stripe).

`studios.stripe_customer_id` is the opaque Stripe customer id, set on the first
Checkout. Nullable (a free studio has none); unique when present so one Stripe
customer maps to one studio. No card data is ever stored.

Reversible by dropping the index then the column: no data rewrite, no backfill.

Revision ID: 0056
Revises: 0055
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("studios", sa.Column("stripe_customer_id", sa.String(64), nullable=True))
    op.create_index(
        "uq_studios_stripe_customer_id",
        "studios",
        ["stripe_customer_id"],
        unique=True,
        postgresql_where=sa.text("stripe_customer_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_studios_stripe_customer_id", table_name="studios")
    op.drop_column("studios", "stripe_customer_id")
