from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class MachineModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """Credential is an opaque token; only its hash is stored, independently
    revocable per machine (TECH/04_AUTH_SYNC_CONTRACT.md, DEC-0003)."""

    __tablename__ = "machines"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    display_name: Mapped[str]
    credential_hash: Mapped[str]
    credential_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
