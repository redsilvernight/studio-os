"""Studio invitations: single-use, expiring, hashed tokens that join a studio.

An invitation is bound to one address and one studio. Only the SHA-256 of the
random secret is stored; the plaintext exists only in the e-mail sent to the
invitee. Consumption is a single conditional UPDATE (`consumed_at IS NULL AND
expires_at > now`), so a secret is never consumed twice.

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050_studio_invitations"
down_revision: str | None = "0049"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "studio_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "studio_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_studio_invitations_role",
        ),
    )
    op.create_index("ix_studio_invitations_studio_id", "studio_invitations", ["studio_id"])
    op.create_index("ix_studio_invitations_email", "studio_invitations", ["email"])


def downgrade() -> None:
    op.drop_index("ix_studio_invitations_email", table_name="studio_invitations")
    op.drop_index("ix_studio_invitations_studio_id", table_name="studio_invitations")
    op.drop_table("studio_invitations")
