"""vault notes: two-scope server vault, typed links, versions, full-text search (P02)

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"

SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('french', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('french', coalesce(summary, '')), 'B') || "
    "setweight(to_tsvector('french', coalesce(body, '')), 'C')"
)
STATUSES = "'draft', 'proposed', 'validated', 'superseded', 'archived'"
AUTHOR_TYPES = "'user', 'agent', 'system'"


def upgrade() -> None:
    op.create_table(
        "vault_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("readable_id", sa.String(), nullable=True),
        sa.Column("note_type", sa.String(), nullable=False, server_default="note"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("author_type", sa.String(), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_SQL, persisted=True),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("scope IN ('studio', 'project')", name="ck_vault_notes_scope"),
        sa.CheckConstraint(
            "(scope = 'project' AND project_id IS NOT NULL)"
            " OR (scope = 'studio' AND project_id IS NULL)",
            name="ck_vault_notes_scope_project",
        ),
        sa.CheckConstraint(
            "note_type IN ('decision', 'rule', 'convention', 'procedure',"
            " 'reference', 'lesson', 'note')",
            name="ck_vault_notes_type",
        ),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_vault_notes_status"),
        sa.CheckConstraint(
            "readable_id IS NULL OR note_type = 'decision'",
            name="ck_vault_notes_readable_id_decision",
        ),
        sa.CheckConstraint(f"author_type IN ({AUTHOR_TYPES})", name="ck_vault_notes_author"),
        sa.CheckConstraint("version >= 1", name="ck_vault_notes_version"),
        sa.CheckConstraint("char_length(content_hash) = 64", name="ck_vault_notes_hash"),
    )
    op.create_index(
        "uq_vault_notes_studio_slug",
        "vault_notes",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("scope = 'studio' AND status <> 'archived'"),
    )
    op.create_index(
        "uq_vault_notes_project_slug",
        "vault_notes",
        ["project_id", "slug"],
        unique=True,
        postgresql_where=sa.text("scope = 'project' AND status <> 'archived'"),
    )
    op.create_index(
        "uq_vault_notes_readable_id",
        "vault_notes",
        ["readable_id"],
        unique=True,
        postgresql_where=sa.text("readable_id IS NOT NULL"),
    )
    op.create_index("ix_vault_notes_project", "vault_notes", ["project_id"])
    op.create_index(
        "ix_vault_notes_search", "vault_notes", ["search_vector"], postgresql_using="gin"
    )
    op.create_index("ix_vault_notes_tags", "vault_notes", ["tags"], postgresql_using="gin")

    op.create_table(
        "vault_note_links",
        sa.Column(
            "source_note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_notes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "target_note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_notes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(), primary_key=True, server_default="links_to"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('links_to', 'relates_to', 'derived_from', 'supersedes')",
            name="ck_vault_note_links_kind",
        ),
        sa.CheckConstraint("source_note_id <> target_note_id", name="ck_vault_note_links_no_self"),
    )
    op.create_index("ix_vault_note_links_target", "vault_note_links", ["target_note_id"])

    op.create_table(
        "vault_note_versions",
        sa.Column(
            "note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_notes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "links",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("author_type", sa.String(), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_vault_note_versions_version"),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_vault_note_versions_status"),
        sa.CheckConstraint(
            f"author_type IN ({AUTHOR_TYPES})", name="ck_vault_note_versions_author"
        ),
    )


def downgrade() -> None:
    op.drop_table("vault_note_versions")
    op.drop_index("ix_vault_note_links_target", table_name="vault_note_links")
    op.drop_table("vault_note_links")
    op.drop_index("ix_vault_notes_tags", table_name="vault_notes")
    op.drop_index("ix_vault_notes_search", table_name="vault_notes")
    op.drop_index("ix_vault_notes_project", table_name="vault_notes")
    op.drop_index("uq_vault_notes_readable_id", table_name="vault_notes")
    op.drop_index("uq_vault_notes_project_slug", table_name="vault_notes")
    op.drop_index("uq_vault_notes_studio_slug", table_name="vault_notes")
    op.drop_table("vault_notes")
