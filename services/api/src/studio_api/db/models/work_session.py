from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class WorkSessionModel(UUIDPKMixin, Base):
    __tablename__ = "work_sessions"

    task_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tasks.id"))
    machine_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("machines.id"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id"), default=None
    )
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
