"""Initial schema — Phase 1 entities (TECH/05_DATA_MODEL.md).

Revision ID: 0001
Revises:
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid_pk() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _timestamp_columns() -> list[sa.Column]:
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
        "users",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "projects",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )

    op.create_table(
        "machines",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("credential_hash", sa.String(), nullable=False),
        sa.Column("credential_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "agents",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id"), nullable=True
        ),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("agent_kind", sa.String(), nullable=False),
    )

    op.create_table(
        "tasks",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("readable_id", sa.String(), nullable=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "claimed_by_machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id"),
            nullable=True,
        ),
        sa.Column(
            "claimed_by_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        sa.UniqueConstraint("readable_id", name="uq_tasks_readable_id"),
    )

    op.create_table(
        "work_sessions",
        _uuid_pk(),
        sa.Column(
            "task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=False
        ),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id"),
            nullable=False,
        ),
        sa.Column(
            "agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=True
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "resource_claims",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True
        ),
        sa.Column("resource_path", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column(
            "claimed_by_machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id"),
            nullable=False,
        ),
        sa.Column(
            "claimed_by_agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "decisions",
        _uuid_pk(),
        *_timestamp_columns(),
        sa.Column("readable_id", sa.String(), nullable=False),
        sa.Column(
            "project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=True
        ),
        sa.Column(
            "task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("proposed_by_type", sa.String(), nullable=False),
        sa.Column("proposed_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.UniqueConstraint("readable_id", name="uq_decisions_readable_id"),
    )

    op.create_table(
        "ai_work_logs",
        _uuid_pk(),
        sa.Column(
            "task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column(
            "machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id"), nullable=True
        ),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("changed_files", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("tests_run", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "events",
        _uuid_pk(),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True
        ),
        sa.Column(
            "machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id"), nullable=True
        ),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_project_id", "events", ["project_id"])

    op.create_table(
        "transfers",
        _uuid_pk(),
        sa.Column("transfer_code", sa.String(), nullable=False),
        sa.Column(
            "sender_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "recipient_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=True
        ),
        sa.Column(
            "task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True
        ),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("transfer_code", name="uq_transfers_transfer_code"),
        sa.UniqueConstraint("object_key", name="uq_transfers_object_key"),
    )

    op.create_table(
        "idempotency_keys",
        _uuid_pk(),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", "endpoint", name="uq_idempotency_endpoint"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("transfers")
    op.drop_index("ix_events_project_id", table_name="events")
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_table("events")
    op.drop_table("ai_work_logs")
    op.drop_table("decisions")
    op.drop_table("resource_claims")
    op.drop_table("work_sessions")
    op.drop_table("tasks")
    op.drop_table("agents")
    op.drop_table("machines")
    op.drop_table("projects")
    op.drop_table("users")
