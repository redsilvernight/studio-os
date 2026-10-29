"""User-scoped durable model identities (DEC-0237).

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"


def upgrade() -> None:
    op.add_column("agents", sa.Column("owner_user_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_agents_identity_owner", "agents", "users", ["owner_user_id"], ["id"])
    op.create_unique_constraint(
        "uq_agents_user_stable_key", "agents", ["owner_user_id", "stable_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_agents_user_stable_key", "agents", type_="unique")
    op.drop_constraint("fk_agents_identity_owner", "agents", type_="foreignkey")
    op.drop_column("agents", "owner_user_id")
