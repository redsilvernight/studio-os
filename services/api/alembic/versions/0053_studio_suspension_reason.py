"""Studio suspension motif (owner request, console fiche C2).

`studios.suspension_reason` is the motif an operator types when suspending a
studio; the mockup labels it "Motif (visible du client)". Nullable: an active
studio has none, and lifting a suspension clears it.

Reversible by a plain column drop: no data rewrite, no backfill.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("studios", sa.Column("suspension_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("studios", "suspension_reason")
