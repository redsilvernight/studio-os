"""task launches: typed request to start a task on a target machine (AIB R2)

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"


def upgrade() -> None:
    op.create_table(
        "task_launches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
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
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("harness_id", sa.String(64), nullable=False),
        sa.Column("agent_stable_key", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="requested"),
        sa.Column("reason_code", sa.String(32), nullable=False, server_default="none"),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_sessions.id"),
            nullable=True,
        ),
        sa.Column("output_excerpt", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_task_launches_machine_status", "task_launches", ["machine_id", "status"])
    op.create_index("ix_task_launches_project", "task_launches", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_task_launches_project", table_name="task_launches")
    op.drop_index("ix_task_launches_machine_status", table_name="task_launches")
    op.drop_table("task_launches")
