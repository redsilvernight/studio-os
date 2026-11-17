"""Project linked repositories (Bloc A): `project_repositories`.

Additive and reversible: one table, one project FK (`CASCADE`), one link
author FK (`SET NULL`), one global uniqueness on the normalized URL. No
backfill (no pre-existing source of linked remotes) and no row rewrite.
Downgrade drops the table.

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_repositories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("normalized_url", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_project_repositories_project_id", "project_repositories", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_repositories_project_id", table_name="project_repositories")
    op.drop_table("project_repositories")
