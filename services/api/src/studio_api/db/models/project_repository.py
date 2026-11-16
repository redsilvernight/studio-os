from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class ProjectRepositoryModel(UUIDPKMixin, Base):
    """A normalized remote URL linked to a project (Bloc A). `normalized_url`
    is globally unique: one remote belongs to at most one project. Rows follow
    their project (`CASCADE`); `created_by` is the linking user, nulled when
    that user disappears (same provenance rule as memberships' `granted_by`)."""

    __tablename__ = "project_repositories"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    normalized_url: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )


ProjectRepository = ProjectRepositoryModel
"""Alias kept for the task wording (`ProjectRepository`): same row type."""
