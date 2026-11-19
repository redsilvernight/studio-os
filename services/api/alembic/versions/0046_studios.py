"""Studios (tenancy root): `studios`, `studio_memberships`, `studio_id` on
top-level resources, operator flag, and per-studio project slugs.

Reversible except for the data rewrite: every pre-existing row is attached to
the seeded internal studio (fixed UUID, `is_internal = true`) and every
existing user becomes its member — `owner` for current instance admins,
`member` otherwise, with system provenance (`granted_by_user_id IS NULL`,
same rule as 0014). `studio_id` is added nullable, backfilled, then made NOT
NULL with a server default on the internal studio, so inserts that do not yet
choose a studio still land in a valid tenant. Tables listed in the spec that
do not exist here are skipped and logged (spec wording "budgets" maps to
`budget_policies`, the project budget row; reservations derive from a policy).

`studio_id` references `studios.id` with `ON DELETE RESTRICT`: a studio that
still owns resources is never deleted implicitly. The internal-studio
`server_default` is TEMPORARY and must be removed once authz and studio
creation set `studio_id` explicitly on every insert.

`projects.slug` becomes unique per studio instead of globally. Downgrade
restores the global uniqueness and therefore refuses to run while two
studios share a slug, listing the offending slugs: resolving them is an
operator decision, never a silent rename.

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-19
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

# Must stay in sync with `studio_api.db.models.studio.INTERNAL_STUDIO_ID`.
INTERNAL_STUDIO_ID = "00000000-0000-0000-0000-000000000001"

# Top-level resources that carry their own `studio_id`. Tasks, events and
# roadmaps inherit it through their project and are deliberately absent.
STUDIO_SCOPED_TABLES = (
    "decisions",
    "vault_notes",
    "library_resources",
    "runtimes",
    "agents",
    "transfers",
    "budget_policies",
)


def _studio_id_column(*, nullable: bool) -> sa.Column[Any]:
    # RESTRICT: a studio that still owns resources cannot be deleted; resources
    # are reattributed explicitly, never silently cascaded away.
    return sa.Column(
        "studio_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("studios.id", ondelete="RESTRICT"),
        nullable=nullable,
    )


def _add_studio_id(bind: Connection, table: str) -> None:
    """Nullable add → backfill to the internal studio → NOT NULL + default."""
    op.add_column(table, _studio_id_column(nullable=True))
    bind.execute(
        sa.text(f"UPDATE {table} SET studio_id = CAST(:studio_id AS uuid) WHERE studio_id IS NULL"),
        {"studio_id": INTERNAL_STUDIO_ID},
    )
    op.alter_column(
        table,
        "studio_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
        # TEMPORARY: the internal-studio server default keeps insert paths that
        # do not know about studios yet valid. Remove it once authz and studio
        # creation are entitled to set studio_id explicitly on every insert.
        server_default=sa.text(f"'{INTERNAL_STUDIO_ID}'"),
    )
    op.create_index(f"ix_{table}_studio_id", table, ["studio_id"])


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
        sa.Column("plan", sa.String(), nullable=False, server_default="free"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
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
            "INSERT INTO studios (id, slug, name, plan, status, is_internal) "
            "VALUES (CAST(:id AS uuid), :slug, :name, 'free', 'active', true)"
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
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_studio_memberships_role",
        ),
    )
    op.create_index("ix_studio_memberships_user_id", "studio_memberships", ["user_id"])

    inserted = bind.execute(
        sa.text(
            "INSERT INTO studio_memberships (studio_id, user_id, role, granted_by_user_id) "
            "SELECT CAST(:studio_id AS uuid), u.id, "
            "CASE WHEN u.role = 'admin' THEN 'owner' ELSE 'member' END, NULL "
            "FROM users u"
        ),
        {"studio_id": INTERNAL_STUDIO_ID},
    ).rowcount
    log.info("0046 backfill: %s memberships on the internal studio", inserted)

    op.add_column(
        "users",
        sa.Column("is_operator", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    _add_studio_id(bind, "projects")
    op.drop_constraint("uq_projects_slug", "projects", type_="unique")
    op.create_unique_constraint("uq_projects_studio_slug", "projects", ["studio_id", "slug"])

    skipped: list[str] = []
    for table in STUDIO_SCOPED_TABLES:
        if sa.inspect(bind).has_table(table):
            _add_studio_id(bind, table)
        else:
            skipped.append(table)
    if skipped:
        log.warning("0046: spec tables not present, studio_id skipped: %s", ", ".join(skipped))


def downgrade() -> None:
    bind = op.get_bind()

    duplicates = bind.execute(
        sa.text("SELECT slug FROM projects GROUP BY slug HAVING count(*) > 1 ORDER BY slug")
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            "0046 downgrade: projects share a slug across studios, resolve them before "
            "downgrading (global uniqueness returns): "
            + ", ".join(str(row[0]) for row in duplicates)
        )

    op.drop_constraint("uq_projects_studio_slug", "projects", type_="unique")
    op.create_unique_constraint("uq_projects_slug", "projects", ["slug"])

    for table in reversed(STUDIO_SCOPED_TABLES):
        if sa.inspect(bind).has_table(table):
            op.drop_index(f"ix_{table}_studio_id", table_name=table)
            op.drop_column(table, "studio_id")

    op.drop_index("ix_projects_studio_id", table_name="projects")
    op.drop_column("projects", "studio_id")
    op.drop_column("users", "is_operator")
    op.drop_index("ix_studio_memberships_user_id", table_name="studio_memberships")
    op.drop_table("studio_memberships")
    op.drop_index("uq_studios_one_internal", table_name="studios")
    op.drop_table("studios")
