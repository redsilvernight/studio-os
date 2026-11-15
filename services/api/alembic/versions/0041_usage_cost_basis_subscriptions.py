"""Usage cost basis and subscriptions (DEC-0361).

`usage_ledger_entries.cost_basis` is a nullable metadata-only column; every
known cost recorded so far is an API-equivalent figure, so the backfill writes
`api_equivalent` where a cost exists. Local estimates priced on a
`public-eur-*` grid were public USD list prices labelled EUR: their currency
becomes USD, amounts untouched. `usage_subscriptions` is a new table. The
downgrade restores the EUR label on those same rows, then drops the column and
the table.

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: str | None = "0040"

_LEDGER = "usage_ledger_entries"
_RELABELLED = "cost_coverage = 'estimated' AND price_list_id LIKE 'public-eur-%'"


def upgrade() -> None:
    op.add_column(_LEDGER, sa.Column("cost_basis", sa.String(32), nullable=True))
    op.execute(f"UPDATE {_LEDGER} SET cost_basis = 'api_equivalent' WHERE cost IS NOT NULL")
    op.execute(
        f"UPDATE {_LEDGER} SET cost_currency = 'USD' WHERE {_RELABELLED} AND cost_currency = 'EUR'"
    )
    op.create_check_constraint(
        "ck_usage_ledger_cost_basis",
        _LEDGER,
        "(cost IS NULL AND cost_basis IS NULL)"
        " OR (cost IS NOT NULL AND cost_basis IN ('measured_billed', 'api_equivalent'))",
    )
    op.create_table(
        "usage_subscriptions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("monthly_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("harnesses", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("providers", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("monthly_price >= 0", name="ck_usage_subscription_price"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_usage_subscription_currency"),
        sa.CheckConstraint(
            "cardinality(harnesses) > 0 OR cardinality(providers) > 0",
            name="ck_usage_subscription_coverage",
        ),
        sa.CheckConstraint(
            "ends_on IS NULL OR ends_on >= starts_on", name="ck_usage_subscription_period"
        ),
    )
    op.create_index("ix_usage_subscriptions_project", "usage_subscriptions", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_subscriptions_project", table_name="usage_subscriptions")
    op.drop_table("usage_subscriptions")
    op.execute(
        f"UPDATE {_LEDGER} SET cost_currency = 'EUR' WHERE {_RELABELLED} AND cost_currency = 'USD'"
    )
    op.drop_constraint("ck_usage_ledger_cost_basis", _LEDGER, type_="check")
    op.drop_column(_LEDGER, "cost_basis")
