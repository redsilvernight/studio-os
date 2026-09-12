from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class EventModel(UUIDPKMixin, Base):
    """`event_id` (== `id`) is client-supplied and unique — replaying the same
    event_id must return the original row, never create a duplicate
    (TECH/04_AUTH_SYNC_CONTRACT.md, TECH/08_OFFLINE_SYNC.md)."""

    __tablename__ = "events"

    event_type: Mapped[str] = mapped_column(index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), default=None
    )
    machine_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("machines.id"), default=None
    )
    actor_type: Mapped[str]
    actor_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    client_timestamp: Mapped[datetime]
    server_timestamp: Mapped[datetime]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    schema_version: Mapped[int] = mapped_column(default=1)
