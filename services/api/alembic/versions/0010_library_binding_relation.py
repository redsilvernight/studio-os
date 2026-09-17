"""Library Bindings P5 (DEC-0067): typed `relation` on `library_resource_links`
plus the inverse index on `to_resource_id`.

Existing rows carry no relation: every couple allowed by the P5 matrix maps
to exactly one relation, so the backfill below is unambiguous. A legacy row
whose couple is outside the matrix keeps NULL and fails the migration loudly
(fail-closed) instead of inventing a meaning — see the guard before the
`SET NOT NULL`.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_BACKFILL_SQL = sa.text(
    """
    UPDATE library_resource_links AS l SET relation = CASE
        WHEN s.kind = 'agent_definition' AND t.kind = 'rule' THEN 'applies_rule'
        WHEN s.kind = 'agent_definition' AND t.kind = 'skill' THEN 'uses_skill'
        WHEN s.kind = 'agent_definition' AND t.kind = 'model_profile'
            THEN 'requires_model_profile'
        WHEN s.kind = 'agent_definition' AND t.kind = 'agent_definition'
            THEN 'composes_agent'
        WHEN s.kind = 'agent_definition' AND t.kind = 'workflow'
            THEN 'references_workflow'
        WHEN s.kind = 'skill' AND t.kind = 'rule' THEN 'refines_skill_rule'
        WHEN s.kind = 'workflow' AND t.kind = 'rule' THEN 'applies_rule'
        WHEN s.kind = 'workflow' AND t.kind = 'skill' THEN 'uses_skill'
        WHEN s.kind = 'workflow' AND t.kind = 'agent_definition'
            THEN 'composes_agent'
        ELSE NULL
    END
    FROM library_resource_versions AS v
    JOIN library_resources AS s ON s.id = v.resource_id,
    library_resources AS t
    WHERE l.from_version_id = v.id AND l.to_resource_id = t.id
    """
)


def upgrade() -> None:
    op.add_column("library_resource_links", sa.Column("relation", sa.String(), nullable=True))
    op.execute(_BACKFILL_SQL)
    remaining = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM library_resource_links WHERE relation IS NULL"))
        .scalar()
    )
    if remaining:
        raise RuntimeError(
            f"0010 blocked: {remaining} legacy library_resource_links row(s) whose "
            "(source kind, target kind) couple has no P5 relation — refusing to "
            "invent a meaning (DEC-0067). Resolve manually before upgrading."
        )
    op.alter_column("library_resource_links", "relation", existing_type=sa.String(), nullable=False)
    op.create_index("ix_library_links_to", "library_resource_links", ["to_resource_id"])


def downgrade() -> None:
    op.drop_index("ix_library_links_to", table_name="library_resource_links")
    op.drop_column("library_resource_links", "relation")
