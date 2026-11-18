from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class InfraMeasurementModel(UUIDPKMixin, Base):
    """One infrastructure cost fact (size or count), never any content.

    `metric` names the fact (`pg_table_bytes`, `storage_bytes`, `sse_connections`,
    `process_rss_bytes`, `backup_bytes`); `subject` narrows it (a table name, empty
    for an instance-wide fact); `project_id` is set only for per-project facts.
    The row is deleted with its project, so a project deletion leaves no trace.
    """

    __tablename__ = "infra_measurements"
    __table_args__ = (Index("ix_infra_measurements_metric_measured_at", "metric", "measured_at"),)

    metric: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(128), default="", server_default="")
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    value: Mapped[int] = mapped_column(BigInteger())
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
