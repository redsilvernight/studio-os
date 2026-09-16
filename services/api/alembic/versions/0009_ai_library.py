"""AI Library canonical domain (P1, DEC-0062/0063/0064): `library_resources`
(active pointer per reusable definition), `library_resource_versions`
(immutable snapshots), `library_resource_links` (version-pinned dependency
edges) and `library_project_locks` (`(project_id, resource_id,
locked_version)` — canonical resource UUID, never `stable_key` alone).

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _timestamp_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _audit_user_column(name: str, nullable: bool = True) -> sa.Column[Any]:
    return sa.Column(
        name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=nullable
    )


def upgrade() -> None:
    op.create_table(
        "library_resources",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("stable_key", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("active_version", sa.Integer(), nullable=False, server_default="0"),
        _audit_user_column("owner_user_id"),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=True,
        ),
        _audit_user_column("created_by_user_id"),
    )
    op.create_index(
        "uq_library_resource_studio",
        "library_resources",
        ["kind", "stable_key"],
        unique=True,
        postgresql_where=sa.text("scope = 'studio'"),
    )
    op.create_index(
        "uq_library_resource_project",
        "library_resources",
        ["kind", "stable_key", "project_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'project'"),
    )
    op.create_index(
        "uq_library_resource_user",
        "library_resources",
        ["kind", "stable_key", "owner_user_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'user'"),
    )
    op.create_index(
        "ix_library_resources_visibility",
        "library_resources",
        ["scope", "owner_user_id", "project_id"],
    )

    op.create_table(
        "library_resource_versions",
        _uuid_pk(),
        sa.Column(
            "resource_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("library_resources.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("content", postgresql.JSONB(), nullable=False, server_default="{}"),
        _audit_user_column("created_by_user_id"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("resource_id", "version", name="uq_library_version_number"),
    )
    op.create_index("ix_library_versions_resource", "library_resource_versions", ["resource_id"])

    op.create_table(
        "library_resource_links",
        _uuid_pk(),
        sa.Column(
            "from_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("library_resource_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "to_resource_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("library_resources.id"),
            nullable=False,
        ),
        sa.Column("to_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("from_version_id", "to_resource_id", name="uq_library_link_edge"),
    )
    op.create_index("ix_library_links_from", "library_resource_links", ["from_version_id"])

    op.create_table(
        "library_project_locks",
        _uuid_pk(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("library_resources.id"),
            nullable=False,
        ),
        sa.Column("locked_version", sa.Integer(), nullable=False),
        _audit_user_column("created_by_user_id"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("project_id", "resource_id", name="uq_library_project_lock"),
    )
    op.create_index("ix_library_locks_project", "library_project_locks", ["project_id"])


def downgrade() -> None:
    op.drop_table("library_project_locks")
    op.drop_table("library_resource_links")
    op.drop_table("library_resource_versions")
    op.drop_table("library_resources")
