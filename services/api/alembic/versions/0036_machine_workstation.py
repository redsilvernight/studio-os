"""machine workstation: attach tool machines to their physical workstation

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-20

Additive (DEC-0226): one nullable self-referencing column and its index, no
backfill — legacy machines stay unattached until their owner attaches them.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"


def upgrade() -> None:
    op.add_column(
        "machines",
        sa.Column("workstation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_machines_workstation_id_machines",
        "machines",
        "machines",
        ["workstation_id"],
        ["id"],
    )
    op.create_index("ix_machines_workstation_id", "machines", ["workstation_id"])


def downgrade() -> None:
    op.drop_index("ix_machines_workstation_id", table_name="machines")
    op.drop_constraint("fk_machines_workstation_id_machines", "machines", type_="foreignkey")
    op.drop_column("machines", "workstation_id")
