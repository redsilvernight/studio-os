from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin
from studio_api.db.models.studio import StudioScopedMixin


class ProjectModel(StudioScopedMixin, UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (sa.UniqueConstraint("studio_id", "slug", name="uq_projects_studio_slug"),)

    slug: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    archived: Mapped[bool] = mapped_column(default=False)
