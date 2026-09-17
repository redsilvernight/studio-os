from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class LibraryResourceModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """Active pointer of one reusable library definition (DEC-0062/0064).

    Canonical identity is the surrogate UUID (all kinds/scopes share the
    same key space); `stable_key` is unique per (kind, scope context) only.
    `active_version == 0` means nothing has been activated yet."""

    __tablename__ = "library_resources"
    __table_args__ = (
        sa.Index(
            "uq_library_resource_studio",
            "kind",
            "stable_key",
            unique=True,
            postgresql_where=sa.text("scope = 'studio'"),
        ),
        sa.Index(
            "uq_library_resource_project",
            "kind",
            "stable_key",
            "project_id",
            unique=True,
            postgresql_where=sa.text("scope = 'project'"),
        ),
        sa.Index(
            "uq_library_resource_user",
            "kind",
            "stable_key",
            "owner_user_id",
            unique=True,
            postgresql_where=sa.text("scope = 'user'"),
        ),
        sa.Index("ix_library_resources_visibility", "scope", "owner_user_id", "project_id"),
    )

    kind: Mapped[str]
    stable_key: Mapped[str]
    scope: Mapped[str]
    status: Mapped[str] = mapped_column(default="draft")
    active_version: Mapped[int] = mapped_column(default=0)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), default=None
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), default=None
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), default=None
    )


class LibraryResourceVersionModel(UUIDPKMixin, Base):
    """One immutable snapshot (DEC-0064): created once, never updated —
    hence no `updated_at`/`version` columns. Dependencies live in
    `library_resource_links`, pinned to explicit versions."""

    __tablename__ = "library_resource_versions"
    __table_args__ = (
        sa.UniqueConstraint("resource_id", "version", name="uq_library_version_number"),
        sa.Index("ix_library_versions_resource", "resource_id"),
    )

    resource_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("library_resources.id")
    )
    version: Mapped[int]
    title: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LibraryResourceLinkModel(UUIDPKMixin, Base):
    """A version-pinned dependency edge: `from_version_id` depends on
    exactly `(to_resource_id, to_version)` (DEC-0064), qualified by a closed
    `relation` vocabulary (P5/DEC-0067). Uniqueness stays on
    `(from_version_id, to_resource_id)`: every allowed kind couple maps to a
    single relation, so no relaxation is needed."""

    __tablename__ = "library_resource_links"
    __table_args__ = (
        sa.UniqueConstraint("from_version_id", "to_resource_id", name="uq_library_link_edge"),
        sa.Index("ix_library_links_from", "from_version_id"),
        sa.Index("ix_library_links_to", "to_resource_id"),
    )

    from_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("library_resource_versions.id")
    )
    to_resource_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("library_resources.id")
    )
    to_version: Mapped[int]
    relation: Mapped[str]


class LibraryProjectLockModel(UUIDPKMixin, Base):
    """A project pins `(resource_id, locked_version)` (DEC-0064 precision 2:
    canonical resource UUID, never `stable_key` alone). Advisory like claims:
    it warns resolution, it never blocks a write."""

    __tablename__ = "library_project_locks"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "resource_id", name="uq_library_project_lock"),
        sa.Index("ix_library_locks_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    resource_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("library_resources.id")
    )
    locked_version: Mapped[int]
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
