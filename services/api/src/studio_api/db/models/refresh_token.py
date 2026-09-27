from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class RefreshTokenModel(UUIDPKMixin, Base):
    """Rotating dashboard refresh token (DEC-0142). Only the SHA-256 of the
    random secret is stored. Each refresh consumes the row and issues a new one
    in the same `family_id`; a consumed row presented again revokes the whole
    family. `auth_version` is the User's value at login: any later increment
    (password, disable, role, revoke-sessions) makes the family unusable."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    machine_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE")
    )
    family_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(unique=True)
    auth_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_refresh_tokens_family", RefreshTokenModel.family_id)
Index("ix_refresh_tokens_user", RefreshTokenModel.user_id)
