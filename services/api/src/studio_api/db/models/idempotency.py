from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class IdempotencyStatus:
    PENDING = "pending"
    COMPLETED = "completed"


class IdempotencyKeyModel(UUIDPKMixin, Base):
    """Backs the `Idempotency-Key` header on replayable creation endpoints
    (.claude/rules/contracts.md): same key + endpoint replays the stored
    response instead of re-running the create.

    The unique constraint on (idempotency_key, endpoint) is also the
    concurrency primitive: a row is inserted with `status=pending` *before*
    the business creation runs, so two concurrent requests race on this
    insert at the database level rather than on the business row."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("idempotency_key", "endpoint", name="uq_idempotency_endpoint"),
    )

    idempotency_key: Mapped[str]
    endpoint: Mapped[str]
    request_hash: Mapped[str]
    status: Mapped[str]
    response_status: Mapped[int | None]
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
