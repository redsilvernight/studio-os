"""Roadmaps P2 (DEC-0084/DEC-0085): `roadmaps`, `roadmap_phases`,
`roadmap_steps`, `roadmap_step_dependencies`, `roadmap_step_task_links`,
`roadmap_revisions`. Purely additive: no existing table is altered (no
`roadmap_id` on `tasks`, a Task keeps existing without any Roadmap). At most
one `active` roadmap per project (partial unique index).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _fk(name: str, target: str, *, nullable: bool = False, ondelete: str | None = None) -> Any:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
    )


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _version() -> sa.Column[Any]:
    return sa.Column("version", sa.Integer(), nullable=False, server_default="1")


def _provenance() -> list[Any]:
    return [
        sa.Column("origin", sa.String(), nullable=False, server_default="manual"),
        sa.Column("actor_type", sa.String(), nullable=False, server_default="user"),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        _fk("agent_id", "agents.id", nullable=True),
        _fk("machine_id", "machines.id", nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "roadmaps",
        _uuid_pk(),
        *_timestamps(),
        _version(),
        _fk("project_id", "projects.id"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=True),
        sa.Column("context", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("revision_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approved_revision_no", sa.Integer(), nullable=True),
        *_provenance(),
    )
    op.create_index("ix_roadmaps_project_id", "roadmaps", ["project_id"])
    op.create_index(
        "uq_roadmaps_one_active_per_project",
        "roadmaps",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "roadmap_phases",
        _uuid_pk(),
        *_timestamps(),
        _version(),
        _fk("roadmap_id", "roadmaps.id", ondelete="CASCADE"),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=True),
        *_provenance(),
        sa.UniqueConstraint("roadmap_id", "key", name="uq_roadmap_phases_key"),
    )
    op.create_index("ix_roadmap_phases_roadmap_id", "roadmap_phases", ["roadmap_id"])

    op.create_table(
        "roadmap_steps",
        _uuid_pk(),
        *_timestamps(),
        _version(),
        _fk("roadmap_id", "roadmaps.id", ondelete="CASCADE"),
        _fk("phase_id", "roadmap_phases.id", ondelete="CASCADE"),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=True),
        sa.Column("context", sa.String(), nullable=True),
        sa.Column("instructions", sa.String(), nullable=True),
        sa.Column("acceptance_criteria", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("criteria_checked", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("task_plan", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("state_override", sa.String(), nullable=True),
        sa.Column("state_override_reason", sa.String(), nullable=True),
        *_provenance(),
        sa.UniqueConstraint("roadmap_id", "key", name="uq_roadmap_steps_key"),
    )
    op.create_index("ix_roadmap_steps_roadmap_id", "roadmap_steps", ["roadmap_id"])
    op.create_index("ix_roadmap_steps_phase_id", "roadmap_steps", ["phase_id"])

    op.create_table(
        "roadmap_step_dependencies",
        sa.Column(
            "step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roadmap_steps.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roadmap_steps.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        _fk("roadmap_id", "roadmaps.id", ondelete="CASCADE"),
        sa.CheckConstraint("step_id <> depends_on_step_id", name="ck_roadmap_dep_not_self"),
    )
    op.create_index(
        "ix_roadmap_step_dependencies_roadmap_id", "roadmap_step_dependencies", ["roadmap_id"]
    )

    op.create_table(
        "roadmap_step_task_links",
        _uuid_pk(),
        _fk("step_id", "roadmap_steps.id", ondelete="CASCADE"),
        _fk("task_id", "tasks.id"),
        sa.Column("hydration_key", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *_provenance(),
        sa.UniqueConstraint("step_id", "task_id", name="uq_roadmap_link_step_task"),
    )
    op.create_index("ix_roadmap_step_task_links_step_id", "roadmap_step_task_links", ["step_id"])
    op.create_index("ix_roadmap_step_task_links_task_id", "roadmap_step_task_links", ["task_id"])
    op.create_index(
        "uq_roadmap_link_step_hydration_key",
        "roadmap_step_task_links",
        ["step_id", "hydration_key"],
        unique=True,
        postgresql_where=sa.text("hydration_key IS NOT NULL"),
    )

    op.create_table(
        "roadmap_revisions",
        _uuid_pk(),
        _fk("roadmap_id", "roadmaps.id", ondelete="CASCADE"),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("base_revision_no", sa.Integer(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("content", postgresql.JSONB(), nullable=True),
        _fk("reviewed_by_user_id", "users.id", nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *_provenance(),
    )
    op.create_index("ix_roadmap_revisions_roadmap_id", "roadmap_revisions", ["roadmap_id"])
    op.create_index(
        "uq_roadmap_revision_no_per_kind",
        "roadmap_revisions",
        ["roadmap_id", "revision_no", "kind"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("roadmap_revisions")
    op.drop_table("roadmap_step_task_links")
    op.drop_table("roadmap_step_dependencies")
    op.drop_table("roadmap_steps")
    op.drop_table("roadmap_phases")
    op.drop_table("roadmaps")
