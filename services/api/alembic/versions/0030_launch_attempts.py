"""task launches: attempt chain and retry trace (P02 recovery)

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"


def upgrade() -> None:
    op.add_column(
        "task_launches",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "task_launches",
        sa.Column("retry_of_launch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_task_launches_retry_of",
        "task_launches",
        "task_launches",
        ["retry_of_launch_id"],
        ["id"],
    )
    # One retry per attempt: a second (concurrent) retry of the same attempt
    # can never insert a twin; the service resolves it to the existing one.
    op.create_index(
        "uq_task_launches_retry_of",
        "task_launches",
        ["retry_of_launch_id"],
        unique=True,
        postgresql_where=sa.text("retry_of_launch_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_task_launches_retry_of", table_name="task_launches")
    op.drop_constraint("fk_task_launches_retry_of", "task_launches", type_="foreignkey")
    op.drop_column("task_launches", "retry_of_launch_id")
    op.drop_column("task_launches", "attempt")
