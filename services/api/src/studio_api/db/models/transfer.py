from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, UUIDPKMixin


class TransferModel(UUIDPKMixin, Base):
    """Exact field list per .claude/rules/database.md — do not add a field here
    without adding it to TECH/05_DATA_MODEL.md and packages/studio-contracts
    first (contract-change process)."""

    __tablename__ = "transfers"

    transfer_code: Mapped[str] = mapped_column(unique=True)
    sender_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), default=None
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), default=None
    )
    # Optional link to the build this artefact came from (DEC-0059, 9.1) —
    # additive, nullable, quotas and Transfer authorization unchanged.
    build_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("builds.id"), default=None
    )
    category: Mapped[str]
    filename: Mapped[str]
    object_key: Mapped[str] = mapped_column(unique=True)
    content_type: Mapped[str]
    # BIGINT: a large build/recording transfer can exceed 32-bit INTEGER range.
    size_bytes: Mapped[int] = mapped_column(BigInteger())
    sha256: Mapped[str | None] = mapped_column(default=None)
    # Base64 MD5 (RFC 1864) presigned into the PUT (single-PUT path only) so
    # MinIO/S3 rejects a byte mismatch at upload time — see DEC-0025.
    content_md5: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="created")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
