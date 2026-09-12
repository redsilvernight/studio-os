from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class AIWorkLogModel(UUIDPKMixin, Base):
    __tablename__ = "ai_work_logs"

    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), default=None
    )
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    agent_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("agents.id"))
    machine_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("machines.id"), default=None
    )
    summary: Mapped[str]
    status: Mapped[str] = mapped_column(default="started")
    changed_files: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    tests_run: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
