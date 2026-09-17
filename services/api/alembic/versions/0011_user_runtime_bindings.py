"""User/Runtime Bindings P4 (DEC-0068): `runtime_bindings` (stored per-user,
project and studio runtime choices for logical library keys, plus
non-secret target payloads).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "runtime_bindings",
        _uuid_pk(),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=True,
        ),
        sa.Column("target_kind", sa.String(), nullable=False),
        sa.Column("target_stable_key", sa.String(), nullable=False),
        sa.Column("target", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "uq_runtime_binding_user",
        "runtime_bindings",
        ["level", "owner_user_id", "target_kind", "target_stable_key"],
        unique=True,
        postgresql_where=sa.text("level = 'user'"),
    )
    op.create_index(
        "uq_runtime_binding_project",
        "runtime_bindings",
        ["level", "project_id", "target_kind", "target_stable_key"],
        unique=True,
        postgresql_where=sa.text("level IN ('project_override', 'project_default')"),
    )
    op.create_index(
        "uq_runtime_binding_studio",
        "runtime_bindings",
        ["level", "target_kind", "target_stable_key"],
        unique=True,
        postgresql_where=sa.text("level = 'studio_default'"),
    )
    op.create_index("ix_runtime_bindings_owner", "runtime_bindings", ["owner_user_id"])
    op.create_index("ix_runtime_bindings_project", "runtime_bindings", ["project_id"])


def downgrade() -> None:
    op.drop_table("runtime_bindings")
