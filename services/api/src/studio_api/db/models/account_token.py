from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class AccountTokenPurpose:
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class AccountTokenModel(UUIDPKMixin, Base):
    """Single-use account secret (A4, DU-0/A): e-mail verification or
    password reset. Only the SHA-256 of the random secret is stored; the
    secret itself exists only in the e-mail sent to the User. Consumption is a
    single conditional UPDATE (`consumed_at IS NULL AND expires_at > now`), so
    a secret is never consumed twice."""

    __tablename__ = "account_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    purpose: Mapped[str]
    token_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_account_tokens_user_purpose", AccountTokenModel.user_id, AccountTokenModel.purpose)
