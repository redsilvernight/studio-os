"""Session cycle and account state (A2, DEC-0110 / DEC-0121).

`users.auth_version` is bumped by every revocation (password change, disable,
role change, revoke-sessions) and compared with the JWT claim of the same
name. `disabled_at` and `email_verified_at` carry the account state
(`disabled` > `pending` > `active`). Backfill: every existing User is
verified at its creation date, so enforcement is neutral at activation.
Downgrade drops the three columns.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE users SET email_verified_at = created_at")


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "auth_version")
