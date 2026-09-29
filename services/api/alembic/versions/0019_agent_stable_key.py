"""Agent stable key (AIB-I): local stable key set by `agents ensure`
(`agents-ensure-{harness}` by default), unique per owning machine — the
idempotent lookup key for session-start. Never an authorization input, never
`AgentDefinition.stable_key`.

Purely additive: a nullable column plus a unique constraint (NULLs stay
distinct, so existing rows are untouched). Downgrade drops the constraint
and the column.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("stable_key", sa.String(), nullable=True))
    op.create_unique_constraint(
        "uq_agents_machine_stable_key", "agents", ["machine_id", "stable_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_agents_machine_stable_key", "agents", type_="unique")
    op.drop_column("agents", "stable_key")
