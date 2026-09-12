from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class ProjectModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "projects"

    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    archived: Mapped[bool] = mapped_column(default=False)
