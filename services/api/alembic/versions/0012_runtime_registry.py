"""Runtime Registry P6 (DEC-0070): `runtimes` (declared runtimes with stable
UUID identity, open harness/provider/model refs, declared capabilities,
logical revocation). Purely additive: `runtime_bindings` rows are untouched
and stay valid (P4 inline targets keep resolving without a registry row).

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "runtimes",
        _uuid_pk(),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id"),
            nullable=True,
        ),
        sa.Column("harness_ref", sa.String(200), nullable=True),
        sa.Column("provider_ref", sa.String(200), nullable=True),
        sa.Column("model_ref", sa.String(200), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("capability_source", sa.String(32), nullable=False, server_default="declared"),
        sa.Column("runtime_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_runtimes_owner", "runtimes", ["owner_user_id"])
    op.create_index("ix_runtimes_machine", "runtimes", ["machine_id"])
    op.create_index("ix_runtimes_status", "runtimes", ["status"])


def downgrade() -> None:
    op.drop_table("runtimes")
