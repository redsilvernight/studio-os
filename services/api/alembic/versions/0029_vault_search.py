"""vault search: note anchors (path/task) and readable_id in the search vector (P04)

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"

SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('french', coalesce(readable_id, '')), 'A') || "
    "setweight(to_tsvector('french', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('french', coalesce(summary, '')), 'B') || "
    "setweight(to_tsvector('french', coalesce(body, '')), 'C')"
)
PREVIOUS_SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('french', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('french', coalesce(summary, '')), 'B') || "
    "setweight(to_tsvector('french', coalesce(body, '')), 'C')"
)


def _replace_search_vector(expression: str) -> None:
    op.drop_index("ix_vault_notes_search", table_name="vault_notes")
    op.drop_column("vault_notes", "search_vector")
    op.add_column(
        "vault_notes",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(expression, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_vault_notes_search", "vault_notes", ["search_vector"], postgresql_using="gin"
    )


def upgrade() -> None:
    op.add_column(
        "vault_notes",
        sa.Column(
            "anchors",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
    )
    op.create_index("ix_vault_notes_anchors", "vault_notes", ["anchors"], postgresql_using="gin")
    op.add_column(
        "vault_note_versions",
        sa.Column(
            "anchors",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
    )
    _replace_search_vector(SEARCH_VECTOR_SQL)


def downgrade() -> None:
    _replace_search_vector(PREVIOUS_SEARCH_VECTOR_SQL)
    op.drop_column("vault_note_versions", "anchors")
    op.drop_index("ix_vault_notes_anchors", table_name="vault_notes")
    op.drop_column("vault_notes", "anchors")
