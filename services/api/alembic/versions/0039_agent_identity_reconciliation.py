"""Explicit reversible reconciliation of legacy agent identities (DEC-0237).

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"


def upgrade() -> None:
    op.add_column("agents", sa.Column("superseded_by_agent_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_agents_superseded_by",
        "agents",
        "agents",
        ["superseded_by_agent_id"],
        ["id"],
    )
    op.create_index("ix_agents_superseded_by_agent_id", "agents", ["superseded_by_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agents_superseded_by_agent_id", table_name="agents")
    op.drop_constraint("fk_agents_superseded_by", "agents", type_="foreignkey")
    op.drop_column("agents", "superseded_by_agent_id")
