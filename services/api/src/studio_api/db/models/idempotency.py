from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class IdempotencyKeyModel(UUIDPKMixin, Base):
    """Backs the `Idempotency-Key` header on replayable creation endpoints
    (.claude/rules/contracts.md): same key + endpoint replays the stored
    response instead of re-running the create."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("idempotency_key", "endpoint", name="uq_idempotency_endpoint"),
    )

    idempotency_key: Mapped[str]
    endpoint: Mapped[str]
    request_hash: Mapped[str]
    response_status: Mapped[int]
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
