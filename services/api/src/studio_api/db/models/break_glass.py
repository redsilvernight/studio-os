"""Break-glass exception access (0055, DEC-0384).

An operator asks for a bounded, client-visible access window; the studio owner
decides. `break_glass_audit` is append-only (a database trigger refuses UPDATE
and DELETE) and never holds client content: only the transition, who acted and
when.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin

MAX_BREAK_GLASS_HOURS = 24


class BreakGlassScope(StrEnum):
    """What the operator may consult. There is deliberately no `content`."""

    METADATA = "metadata"
    SUPPORT = "support"


class BreakGlassStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"


class BreakGlassAuditEvent(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"


class BreakGlassRequestModel(UUIDPKMixin, Base):
    __tablename__ = "break_glass_requests"
    __table_args__ = (
        sa.CheckConstraint(
            "scope IN ('metadata', 'support')", name="ck_break_glass_requests_scope"
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'approved', 'denied', 'expired', 'revoked')",
            name="ck_break_glass_requests_status",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR "
            "(decided_at IS NOT NULL AND expires_at <= decided_at + interval '24 hours')",
            name="ck_break_glass_requests_window",
        ),
        sa.Index("ix_break_glass_requests_studio_id", "studio_id"),
        sa.Index("ix_break_glass_requests_status", "studio_id", "status"),
    )

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("studios.id", ondelete="CASCADE")
    )
    operator_ref: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column()
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(default=BreakGlassStatus.REQUESTED.value)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BreakGlassAuditModel(UUIDPKMixin, Base):
    __tablename__ = "break_glass_audit"
    __table_args__ = (
        sa.CheckConstraint(
            "event IN ('requested', 'approved', 'denied', 'expired', 'revoked')",
            name="ck_break_glass_audit_event",
        ),
        sa.Index("ix_break_glass_audit_studio_at", "studio_id", "at"),
        sa.Index("ix_break_glass_audit_request_id", "request_id"),
    )

    event: Mapped[str] = mapped_column()
    request_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    studio_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    actor: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
