from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class TaskLaunchModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """Typed request to start a task on a target machine (AIB R2, DEC-0173).

    Data only, never a command: ids and stable keys. Status moves only
    through `studio_contracts.task_launch.ALLOWED_TRANSITIONS`.
    """

    __tablename__ = "task_launches"

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    task_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tasks.id"))
    machine_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("machines.id"))
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id")
    )
    harness_id: Mapped[str] = mapped_column(String(64))
    agent_stable_key: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(String(16), default="requested")
    reason_code: Mapped[str] = mapped_column(String(32), default="none")
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("work_sessions.id"), default=None
    )
    output_excerpt: Mapped[str | None] = mapped_column(default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
