"""Drop the temporary internal-studio default on `studio_id` (0046 follow-up).

Authz and studio creation now set `studio_id` explicitly on every insert, so an
insert that forgets it fails (NOT NULL) instead of silently landing in the
internal studio. The downgrade restores the default of 0046.

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

INTERNAL_STUDIO_ID = "00000000-0000-0000-0000-000000000001"
STUDIO_SCOPED_TABLES = (
    "decisions",
    "vault_notes",
    "library_resources",
    "runtimes",
    "agents",
    "transfers",
    "budget_policies",
    "projects",
)


def upgrade() -> None:
    for table in STUDIO_SCOPED_TABLES:
        op.alter_column(table, "studio_id", server_default=None)


def downgrade() -> None:
    for table in STUDIO_SCOPED_TABLES:
        op.alter_column(table, "studio_id", server_default=sa.text(f"'{INTERNAL_STUDIO_ID}'"))
