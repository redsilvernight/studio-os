from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin

INTERNAL_STUDIO_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
"""Tenant owning every resource created before studios existed (0046). New
resources default to it until per-request studio selection exists."""

PENDING_DELETION_STATUS = "pending_deletion"
"""Read-only state between a deletion request and its grace-window end (0051).
Never gates reads or the export/cancel routes; every other write is refused."""


class StudioRole(StrEnum):
    """A User's role inside one studio (0046 `studio_memberships.role`), weakest
    to strongest. It decides studio management and project reach; the account
    `Role` (readonly|agent|developer|admin) keeps governing machine/agent
    capabilities and grants no implicit project reach any more."""

    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


class StudioScopedMixin:
    """`studio_id` carried by every top-level resource (0046). NOT NULL, no
    default (0049): every insert chooses its studio explicitly."""

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="RESTRICT"),
        index=True,
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
        sa.Index(
            "ix_studios_deletion_scheduled_at",
            "deletion_scheduled_at",
            postgresql_where=sa.text("deletion_scheduled_at IS NOT NULL"),
        ),
    )

    slug: Mapped[str]
    name: Mapped[str]
    plan: Mapped[str] = mapped_column(default="free", server_default="free")
    # `pending_deletion` is the read-only state between a deletion request and
    # its grace-window end (0051). It never gates the export or the cancel
    # routes; every other write is refused.
    status: Mapped[str] = mapped_column(default="active", server_default="active")
    is_internal: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Deletion grace window (0051). Both NULL while no deletion is scheduled;
    # `purge_due_studios` deletes a studio once `deletion_scheduled_at` passed.
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


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


class StudioInvitationModel(UUIDPKMixin, Base):
    """Pending invitation to one studio for one address (0050). Only the
    SHA-256 of the random secret is stored; consumption is a single
    conditional UPDATE, so a secret joins at most once. `email` is stored
    normalized (trimmed, lower-cased) and is the account the invitation
    targets: possessing the link is not enough if the caller's account uses
    another address."""

    __tablename__ = "studio_invitations"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_studio_invitations_role",
        ),
    )

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("studios.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(default="member", server_default="member")
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
