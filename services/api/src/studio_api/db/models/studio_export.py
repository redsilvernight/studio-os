from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class StudioExportModel(UUIDPKMixin, Base):
    """One export archive of a studio (0051): the row records where the
    archive lives in object storage, who asked for it and until when a
    presigned link may be issued. The archive itself is never stored in the
    database and never expires by itself — `expires_at` only bounds the
    download window, `purge_due_studios` removes the object with the studio.

    `requested_by_user_id` is nullable so deleting the requester's account
    keeps the audit row (`ON DELETE SET NULL`)."""

    __tablename__ = "studio_exports"

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="CASCADE"),
        index=True,
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    object_key: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
