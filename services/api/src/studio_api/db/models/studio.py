from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin

INTERNAL_STUDIO_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
"""Tenant owning every resource created before studios existed (0046). New
projects default to it until per-request studio selection exists."""


class StudioModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """Top-level tenant (0046): the root above projects. `is_internal` marks
    the single seeded studio that owns pre-existing data; it is deliberately
    not deletable by ordinary code paths."""

    __tablename__ = "studios"

    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    is_internal: Mapped[bool] = mapped_column(default=False, server_default="false")


class StudioMembershipModel(Base):
    """Where a User may act at studio level (same binary, deny-by-default
    model as `project_memberships`, DEC-0103 §1). `granted_by_user_id` is NULL
    only for the 0046 backfill; every application grant keeps who gave it."""

    __tablename__ = "studio_memberships"

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("studios.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
