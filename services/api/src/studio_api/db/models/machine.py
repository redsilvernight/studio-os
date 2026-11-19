from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class MachineModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """Credential is an opaque token; only its hash is stored, independently
    revocable per machine (TECH/04_AUTH_SYNC_CONTRACT.md, DEC-0003).

    `studio_id` is the studio this machine last selected (0047). It is
    nullable on purpose: a machine that never chose one falls back to the
    studio resolution default instead of being pinned to a tenant."""

    __tablename__ = "machines"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    display_name: Mapped[str]
    credential_hash: Mapped[str]
    credential_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    studio_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="RESTRICT"),
        default=None,
        index=True,
    )
    workstation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("machines.id"), default=None, index=True
    )
    capabilities_reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
