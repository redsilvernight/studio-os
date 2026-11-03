"""execution snapshots: immutable effective configuration per launch (DEC-0199)

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-13

Additive: one new table, nothing existing is altered. No foreign key towards
Library resources or runtime bindings (references and digests only).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | None = "0031"

TABLE = "execution_snapshots"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "task_launch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_launches.id"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("capture_status", sa.String(16), nullable=False),
        sa.Column("capture_reason", sa.String(500), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_launch_id", name="uq_execution_snapshots_launch"),
        sa.CheckConstraint(
            "capture_status IN ('ok', 'partial', 'failed')",
            name="ck_execution_snapshots_status",
        ),
        sa.CheckConstraint(
            "(capture_status = 'ok') = (capture_reason IS NULL)",
            name="ck_execution_snapshots_reason",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_execution_snapshots_hash"
        ),
        sa.CheckConstraint("retention_until > created_at", name="ck_execution_snapshots_retention"),
    )
    op.create_index("ix_execution_snapshots_content_hash", TABLE, ["content_hash"])
    op.create_index("ix_execution_snapshots_retention", TABLE, ["retention_until"])
    op.create_index("ix_execution_snapshots_project", TABLE, ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_execution_snapshots_project", table_name=TABLE)
    op.drop_index("ix_execution_snapshots_retention", table_name=TABLE)
    op.drop_index("ix_execution_snapshots_content_hash", table_name=TABLE)
    op.drop_table(TABLE)
