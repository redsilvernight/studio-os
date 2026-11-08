"""Library `derived_from` (P50a/D1): a user version names the common version it
derives from. Additive and reversible: two nullable columns, one FK, one
pair-consistency check; no backfill and no row rewrite (metadata-only
`ADD COLUMN` on PostgreSQL, so no long lock on a populated table).

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"

_TABLE = "library_resource_versions"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("derived_from_resource_id", sa.UUID(), nullable=True))
    op.add_column(_TABLE, sa.Column("derived_from_version", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_library_version_derived_from_resource",
        _TABLE,
        "library_resources",
        ["derived_from_resource_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_library_version_derived_from_pair",
        _TABLE,
        "(derived_from_resource_id IS NULL) = (derived_from_version IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_library_version_derived_from_pair", _TABLE, type_="check")
    op.drop_constraint("fk_library_version_derived_from_resource", _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, "derived_from_version")
    op.drop_column(_TABLE, "derived_from_resource_id")
