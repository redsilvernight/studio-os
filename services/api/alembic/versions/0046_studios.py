"""Studios (tenancy root): `studios`, `studio_memberships`, `projects.studio_id`.

Reversible and additive except for `projects.studio_id`, which the migration
backfills. The seeded internal studio (fixed UUID, `is_internal = true`) owns
every resource that existed before studios: all projects point at it and all
existing users become its members (system provenance: `granted_by_user_id IS
NULL`, exactly like the 0014 backfill). `projects.studio_id` is NOT NULL with
a server default on the internal studio, so a project created before the
per-request studio selection exists still lands in a valid tenant. Downgrade
drops the column then the two tables.

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-19
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

# Must stay in sync with `studio_api.db.models.studio.INTERNAL_STUDIO_ID`.
INTERNAL_STUDIO_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "studios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("slug", name="uq_studios_slug"),
    )
    op.create_index(
        "uq_studios_one_internal",
        "studios",
        ["is_internal"],
        unique=True,
        postgresql_where=sa.text("is_internal"),
    )

    bind.execute(
        sa.text(
            "INSERT INTO studios (id, slug, name, is_internal) "
            "VALUES (CAST(:id AS uuid), :slug, :name, true)"
        ),
        {"id": INTERNAL_STUDIO_ID, "slug": "studio-os", "name": "Studio OS"},
    )

    op.create_table(
        "studio_memberships",
        sa.Column(
            "studio_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_studio_memberships_user_id", "studio_memberships", ["user_id"])

    inserted = bind.execute(
        sa.text(
            "INSERT INTO studio_memberships (studio_id, user_id, granted_by_user_id) "
            "SELECT CAST(:studio_id AS uuid), u.id, NULL FROM users u"
        ),
        {"studio_id": INTERNAL_STUDIO_ID},
    ).rowcount
    log.info("0046 backfill: %s memberships on the internal studio", inserted)

    op.add_column(
        "projects",
        sa.Column(
            "studio_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studios.id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{INTERNAL_STUDIO_ID}'"),
        ),
    )
    op.create_index("ix_projects_studio_id", "projects", ["studio_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_studio_id", table_name="projects")
    op.drop_column("projects", "studio_id")
    op.drop_index("ix_studio_memberships_user_id", table_name="studio_memberships")
    op.drop_table("studio_memberships")
    op.drop_index("uq_studios_one_internal", table_name="studios")
    op.drop_table("studios")
