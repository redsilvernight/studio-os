"""Central usage price lists (DEC-0362).

`usage_price_lists` is a new table of immutable, dated price grids
(`project_id` NULL = global). Nothing is backfilled: until a grid is
published, daemons keep their bundled one. The downgrade drops the table;
ledger entries keep their `price_list_id` string either way.

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"


def upgrade() -> None:
    op.create_table(
        "usage_price_lists",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("price_list_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("models", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("price_list_id", name="uq_usage_price_lists_price_list_id"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_usage_price_list_currency"),
    )
    op.create_index(
        "ix_usage_price_lists_scope", "usage_price_lists", ["project_id", "effective_from"]
    )


def downgrade() -> None:
    op.drop_index("ix_usage_price_lists_scope", table_name="usage_price_lists")
    op.drop_table("usage_price_lists")
