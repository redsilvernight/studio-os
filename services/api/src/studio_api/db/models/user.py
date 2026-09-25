from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class UserModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "users"

    display_name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)
    role: Mapped[str]
    password_hash: Mapped[str | None] = mapped_column(nullable=True)
    auth_version: Mapped[int] = mapped_column(default=0, server_default="0")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def is_active(self) -> bool:
        return self.disabled_at is None and self.email_verified_at is not None
