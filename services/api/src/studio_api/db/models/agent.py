from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class AgentModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("machine_id", "stable_key", name="uq_agents_machine_stable_key"),
    )

    machine_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("machines.id"), default=None
    )
    display_name: Mapped[str]
    agent_kind: Mapped[str]
    agent_profile: Mapped[str | None] = mapped_column(String(), default=None)
    harness: Mapped[str | None] = mapped_column(String(), default=None)
    provider: Mapped[str | None] = mapped_column(String(), default=None)
    model: Mapped[str | None] = mapped_column(String(), default=None)
    stable_key: Mapped[str | None] = mapped_column(String(), default=None)
