from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin

INTERNAL_STUDIO_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
"""Tenant owning every resource created before studios existed (0046). New
resources default to it until per-request studio selection exists."""


class StudioScopedMixin:
    """`studio_id` carried by every top-level resource (0046). NOT NULL with a
    server default on the internal studio, so an insert that does not choose a
    studio still lands in a valid tenant."""

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="RESTRICT"),
        index=True,
        server_default=sa.text(f"'{INTERNAL_STUDIO_ID}'"),
    )


class StudioModel(UUIDPKMixin, TimestampMixin, VersionMixin, Base):
    """Top-level tenant (0046): the root above projects. `is_internal` marks
    the single seeded studio that owns pre-existing data; it is deliberately
    not deletable by ordinary code paths."""

    __tablename__ = "studios"
    __table_args__ = (
        sa.UniqueConstraint("slug", name="uq_studios_slug"),
        sa.Index(
            "uq_studios_one_internal",
            "is_internal",
            unique=True,
            postgresql_where=sa.text("is_internal"),
        ),
    )

    slug: Mapped[str]
    name: Mapped[str]
    plan: Mapped[str] = mapped_column(default="free", server_default="free")
    status: Mapped[str] = mapped_column(default="active", server_default="active")
    is_internal: Mapped[bool] = mapped_column(default=False, server_default="false")


class StudioMembershipModel(Base):
    """Where a User may act at studio level (same deny-by-default model as
    `project_memberships`, DEC-0103 §1), with the role that says what.
    `granted_by_user_id` is NULL only for the 0046 backfill; every application
    grant keeps who gave it. The 0046 backfill promotes current instance
    admins to `owner` and gives everyone else `member`."""

    __tablename__ = "studio_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_studio_memberships_role",
        ),
    )

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("studios.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(default="member", server_default="member")
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
