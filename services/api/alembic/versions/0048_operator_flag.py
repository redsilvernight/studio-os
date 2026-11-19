"""Existing global admins become instance operators.

Instance administration (users, machines, infra, admin CLI) moves from the
global `Role.ADMIN` to `users.is_operator` (DEC-0382). Nobody holds the flag
after 0046, so without this backfill the instance would lock itself.

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE users SET is_operator = true WHERE role = 'admin'")


def downgrade() -> None:
    # shortcut: cannot tell a flag set here from one set by hand, so every
    # global admin loses it; reassign the operators after a downgrade.
    op.execute("UPDATE users SET is_operator = false WHERE role = 'admin'")
