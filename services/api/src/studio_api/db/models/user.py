from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class UserModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "users"

    display_name: Mapped[str]
    email: Mapped[str]
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

    @property
    def status(self) -> str:
        """Derived account state (`studio_contracts.auth.AccountStatus`)."""
        if self.disabled_at is not None:
            return "disabled"
        if self.email_verified_at is None:
            return "pending"
        return "active"


Index("uq_users_email_lower", func.lower(UserModel.email), unique=True)
