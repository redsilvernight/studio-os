"""launch credentials: ephemeral harness credential of a task launch (AIB P9)

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"


def upgrade() -> None:
    op.create_table(
        "launch_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "launch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_launches.id"),
            nullable=False,
        ),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=False
        ),
        sa.Column("credential_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_launch_credentials_hash", "launch_credentials", ["credential_hash"], unique=True
    )
    op.create_index("ix_launch_credentials_launch", "launch_credentials", ["launch_id"])


def downgrade() -> None:
    op.drop_index("ix_launch_credentials_launch", table_name="launch_credentials")
    op.drop_index("ix_launch_credentials_hash", table_name="launch_credentials")
    op.drop_table("launch_credentials")
