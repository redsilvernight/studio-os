"""Announced retention purge of one studio (0054).

Two additive tables, no content:

- `retention_purge_notices` records one announcement per `(studio, kind)`: the
  cutoff chosen from the plan's retention limit, when it was announced and when
  the purge may run (`purge_after`). A notice stays open until `purged_at` is
  set, which is what makes "never purge without an announcement" checkable.
- `retention_purge_log` records, per executed purge, how many rows and objects
  were removed. Counts only: never a title, a note body or a file name.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class RetentionKind(StrEnum):
    """Retention limit applied; the stored value is the plan limit key without
    its `_retention_days` suffix."""

    EVENTS = "events"
    TIMELINE = "timeline"
    USAGE = "usage"
    TRANSFERS = "transfers"
    SNAPSHOTS = "snapshots"


_KIND_CHECK = "kind IN ('events', 'timeline', 'usage', 'transfers', 'snapshots')"


class RetentionPurgeNoticeModel(UUIDPKMixin, Base):
    """Open announcement: data older than `cutoff` is due for deletion once
    `purge_after` passes. `exported_hint` says whether the studio already had
    an export archive when the notice was created."""

    __tablename__ = "retention_purge_notices"
    __table_args__ = (
        CheckConstraint(_KIND_CHECK, name="ck_retention_purge_notices_kind"),
        CheckConstraint("purge_after > announced_at", name="ck_retention_purge_notices_window"),
        Index(
            "uq_retention_purge_notices_open",
            "studio_id",
            "kind",
            unique=True,
            postgresql_where=sa.text("purged_at IS NULL"),
        ),
        Index(
            "ix_retention_purge_notices_due",
            "purge_after",
            postgresql_where=sa.text("purged_at IS NULL"),
        ),
    )

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(sa.String(32))
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    announced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    exported_hint: Mapped[bool] = mapped_column(Boolean(), default=False, server_default=sa.false())


class RetentionPurgeLogModel(UUIDPKMixin, Base):
    """One executed purge, counts only."""

    __tablename__ = "retention_purge_log"
    __table_args__ = (
        CheckConstraint(_KIND_CHECK, name="ck_retention_purge_log_kind"),
        CheckConstraint("rows_deleted >= 0", name="ck_retention_purge_log_rows"),
        CheckConstraint("objects_deleted >= 0", name="ck_retention_purge_log_objects"),
    )

    studio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("studios.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(sa.String(32))
    rows_deleted: Mapped[int] = mapped_column(BigInteger(), default=0, server_default="0")
    objects_deleted: Mapped[int] = mapped_column(BigInteger(), default=0, server_default="0")
    purged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
