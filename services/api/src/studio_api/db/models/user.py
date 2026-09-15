from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class UserModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "users"

    display_name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)
    role: Mapped[str]
    password_hash: Mapped[str | None] = mapped_column(nullable=True)
