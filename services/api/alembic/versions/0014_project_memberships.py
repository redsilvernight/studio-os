"""Project isolation (DEC-0103 / server DEC-0103): `project_memberships`.

Preflight (blocking): every machine must have an existing owner — a machine
without an owner would silently lose every access. Backfill: every existing
User (all roles) gets a membership on every existing project, so enforcement
is neutral at activation; the backfilled rows are exactly the ones with
`granted_by_user_id IS NULL` (system provenance, never an arbitrary admin),
which keeps the generated set auditable. New users and projects created after
this migration start from zero. Downgrade drops the table.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-24
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()
    orphans = bind.execute(
        sa.text(
            "SELECT m.id FROM machines m LEFT JOIN users u ON u.id = m.owner_user_id "
            "WHERE u.id IS NULL"
        )
    ).fetchall()
    if orphans:
        raise RuntimeError(
            "0014 preflight: machines without a valid owner, fix before migrating: "
            + ", ".join(str(row[0]) for row in orphans)
        )
    without_machine = bind.execute(
        sa.text(
            "SELECT u.id FROM users u WHERE NOT EXISTS ("
            "SELECT 1 FROM machines m WHERE m.owner_user_id = u.id "
            "AND m.credential_revoked_at IS NULL)"
        )
    ).fetchall()
    for row in without_machine:
        log.warning("0014 preflight: user %s has no active machine", row[0])

    op.create_table(
        "project_memberships",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
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
    op.create_index("ix_project_memberships_user_id", "project_memberships", ["user_id"])

    inserted = bind.execute(
        sa.text(
            "INSERT INTO project_memberships (project_id, user_id, granted_by_user_id) "
            "SELECT p.id, u.id, NULL FROM projects p CROSS JOIN users u"
        )
    ).rowcount
    log.info("0014 backfill: %s memberships (every user x every project)", inserted)


def downgrade() -> None:
    op.drop_index("ix_project_memberships_user_id", table_name="project_memberships")
    op.drop_table("project_memberships")
