from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin

SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('french', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('french', coalesce(summary, '')), 'B') || "
    "setweight(to_tsvector('french', coalesce(body, '')), 'C')"
)


class VaultNoteModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "vault_notes"

    scope: Mapped[str] = mapped_column(String)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    slug: Mapped[str] = mapped_column(String)
    readable_id: Mapped[str | None] = mapped_column(String, default=None)
    note_type: Mapped[str] = mapped_column(String, default="note")
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="draft")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    content_hash: Mapped[str] = mapped_column(String)
    author_type: Mapped[str] = mapped_column(String)
    author_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR_SQL, persisted=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("scope IN ('studio', 'project')", name="ck_vault_notes_scope"),
        CheckConstraint(
            "(scope = 'project' AND project_id IS NOT NULL)"
            " OR (scope = 'studio' AND project_id IS NULL)",
            name="ck_vault_notes_scope_project",
        ),
        CheckConstraint(
            "note_type IN ('decision', 'rule', 'convention', 'procedure',"
            " 'reference', 'lesson', 'note')",
            name="ck_vault_notes_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'proposed', 'validated', 'superseded', 'archived')",
            name="ck_vault_notes_status",
        ),
        CheckConstraint(
            "readable_id IS NULL OR note_type = 'decision'",
            name="ck_vault_notes_readable_id_decision",
        ),
        CheckConstraint("author_type IN ('user', 'agent', 'system')", name="ck_vault_notes_author"),
        CheckConstraint("version >= 1", name="ck_vault_notes_version"),
        CheckConstraint("char_length(content_hash) = 64", name="ck_vault_notes_hash"),
        Index(
            "uq_vault_notes_studio_slug",
            "slug",
            unique=True,
            postgresql_where=text("scope = 'studio' AND status <> 'archived'"),
        ),
        Index(
            "uq_vault_notes_project_slug",
            "project_id",
            "slug",
            unique=True,
            postgresql_where=text("scope = 'project' AND status <> 'archived'"),
        ),
        Index(
            "uq_vault_notes_readable_id",
            "readable_id",
            unique=True,
            postgresql_where=text("readable_id IS NOT NULL"),
        ),
        Index("ix_vault_notes_project", "project_id"),
        Index("ix_vault_notes_search", "search_vector", postgresql_using="gin"),
        Index("ix_vault_notes_tags", "tags", postgresql_using="gin"),
    )


class VaultNoteLinkModel(Base):
    __tablename__ = "vault_note_links"

    source_note_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vault_notes.id", ondelete="CASCADE"), primary_key=True
    )
    target_note_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vault_notes.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String, primary_key=True, default="links_to")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "kind IN ('links_to', 'relates_to', 'derived_from', 'supersedes')",
            name="ck_vault_note_links_kind",
        ),
        CheckConstraint("source_note_id <> target_note_id", name="ck_vault_note_links_no_self"),
        Index("ix_vault_note_links_target", "target_note_id"),
    )


class VaultNoteVersionModel(Base):
    __tablename__ = "vault_note_versions"

    note_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vault_notes.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    content_hash: Mapped[str] = mapped_column(String)
    change_summary: Mapped[str | None] = mapped_column(Text, default=None)
    author_type: Mapped[str] = mapped_column(String)
    author_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_vault_note_versions_version"),
        CheckConstraint(
            "status IN ('draft', 'proposed', 'validated', 'superseded', 'archived')",
            name="ck_vault_note_versions_status",
        ),
        CheckConstraint(
            "author_type IN ('user', 'agent', 'system')", name="ck_vault_note_versions_author"
        ),
    )
