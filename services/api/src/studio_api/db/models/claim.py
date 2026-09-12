from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin


class ResourceClaimModel(UUIDPKMixin, TimestampMixin, Base):
    """TTL is mandatory; expiry makes a claim inactive regardless of `status`
    (.claude/rules/database.md). Soft lock only — never blocks Git/file writes."""

    __tablename__ = "resource_claims"

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), default=None
    )
    resource_path: Mapped[str]
    resource_type: Mapped[str]
    claimed_by_machine_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("machines.id")
    )
    claimed_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id"), default=None
    )
    status: Mapped[str] = mapped_column(default="active")
    ttl_seconds: Mapped[int]
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
