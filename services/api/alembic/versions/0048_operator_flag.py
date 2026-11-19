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
    # Lossy on purpose: the flag set here cannot be told from one granted by
    # hand afterwards, so the downgrade removes `is_operator` from EVERY global
    # admin. Reassign the operators after a downgrade (then re-upgrade restores
    # the flag for all global admins).
    op.execute("UPDATE users SET is_operator = false WHERE role = 'admin'")
