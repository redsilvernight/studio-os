from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class AgentModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "agents"

    machine_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("machines.id"), default=None
    )
    display_name: Mapped[str]
    agent_kind: Mapped[str]
