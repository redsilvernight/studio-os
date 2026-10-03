from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin


class LaunchCredentialModel(UUIDPKMixin, TimestampMixin, Base):
    """Ephemeral harness credential of one task launch (AIB P9). Only the
    token hash is stored; it resolves to the launch's target machine with a
    scope reduced to the launch's project and an allowlist of operations."""

    __tablename__ = "launch_credentials"
    __table_args__ = (Index("ix_launch_credentials_hash", "credential_hash", unique=True),)

    launch_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("task_launches.id")
    )
    machine_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("machines.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    task_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tasks.id"))
    credential_hash: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
