from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin
from studio_api.db.models.studio import INTERNAL_STUDIO_ID


class ProjectModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "projects"

    # Server default (0046) keeps every project in the seeded internal studio
    # until requests can select a studio explicitly.
    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="CASCADE"),
        index=True,
        server_default=sa.text(f"'{INTERNAL_STUDIO_ID}'"),
    )
    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    archived: Mapped[bool] = mapped_column(default=False)
