from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class ExecutionSnapshotModel(UUIDPKMixin, Base):
    """Immutable execution snapshot of one launch attempt (DEC-0199).

    Written once, never updated — hence no `updated_at`/`version` columns.
    References and digests only: no foreign key towards Library resources or
    runtime bindings, so deleting or archiving a current resource never alters
    a recorded snapshot. `content_hash` is the canonical sha256 of `payload`.
    """

    __tablename__ = "execution_snapshots"
    __table_args__ = (
        UniqueConstraint("task_launch_id", name="uq_execution_snapshots_launch"),
        CheckConstraint(
            "capture_status IN ('ok', 'partial', 'failed')",
            name="ck_execution_snapshots_status",
        ),
        CheckConstraint(
            "(capture_status = 'ok') = (capture_reason IS NULL)",
            name="ck_execution_snapshots_reason",
        ),
        CheckConstraint(
            "content_hash ~ '^sha256:[0-9a-f]{64}$'", name="ck_execution_snapshots_hash"
        ),
        CheckConstraint("retention_until > created_at", name="ck_execution_snapshots_retention"),
        Index("ix_execution_snapshots_content_hash", "content_hash"),
        Index("ix_execution_snapshots_retention", "retention_until"),
        Index("ix_execution_snapshots_project", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    task_launch_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("task_launches.id")
    )
    content_hash: Mapped[str] = mapped_column(String(71))
    schema_version: Mapped[int] = mapped_column(Integer)
    capture_status: Mapped[str] = mapped_column(String(16))
    capture_reason: Mapped[str | None] = mapped_column(String(500), default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
