from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin


class DecisionModel(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "decisions"

    readable_id: Mapped[str] = mapped_column(unique=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), default=None
    )
    title: Mapped[str]
    body: Mapped[str]
    status: Mapped[str] = mapped_column(default="proposed")
    proposed_by_type: Mapped[str]
    proposed_by_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
