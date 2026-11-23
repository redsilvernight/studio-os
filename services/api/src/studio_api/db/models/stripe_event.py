from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base


class StripeEventModel(Base):
    """Stripe webhook event already applied (0057). The primary key is Stripe's
    event id, so a replayed delivery hits the conflict and changes nothing."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(primary_key=True)
    type: Mapped[str]
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
