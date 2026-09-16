"""Studio Producer foundation (roadmap etape 9.1a, DEC-0059): `github_integrations`,
`builds` and `producer_jobs` tables plus the additive nullable
`transfers.build_id` link for build artefacts.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
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


def upgrade() -> None:
    op.create_table(
        "github_integrations",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("repo_full_name", sa.String(), nullable=False),
        sa.Column("default_branch", sa.String(), nullable=False, server_default="main"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
    )

    op.create_table(
        "builds",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id"),
            nullable=True,
        ),
        sa.Column(
            "github_integration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("github_integrations.id"),
            nullable=True,
        ),
        sa.Column("workflow_run_id", sa.BigInteger(), nullable=False),
        sa.Column("workflow_name", sa.String(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("conclusion", sa.String(), nullable=True),
        sa.Column("html_url", sa.String(), nullable=False),
        sa.Column("actor_login", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "workflow_run_id", name="uq_builds_project_workflow_run"),
    )

    op.create_table(
        "producer_jobs",
        _uuid_pk(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="requested"),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id"),
            nullable=True,
        ),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("transfers", sa.Column("build_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_transfers_build_id", "transfers", "builds", ["build_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_transfers_build_id", "transfers", type_="foreignkey")
    op.drop_column("transfers", "build_id")
    op.drop_table("producer_jobs")
    op.drop_table("builds")
    op.drop_table("github_integrations")
