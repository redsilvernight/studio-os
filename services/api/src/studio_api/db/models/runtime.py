from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin


class RuntimeBindingModel(UUIDPKMixin, TimestampMixin, Base):
    """A stored runtime choice for a logical library key (P4/DEC-0068).

    Never a Library Binding: the key is `(target_kind, target_stable_key)`,
    logical and version-free, and the payload is a concrete non-secret
    runtime target. `owner_user_id` is always the creating user; visibility
    differs by level (`user` = owner-or-admin, shared levels = all
    authenticated readers, like project library resources). `session`
    overrides are never stored — the `level` column only ever holds the four
    stored levels."""

    __tablename__ = "runtime_bindings"
    __table_args__ = (
        sa.Index(
            "uq_runtime_binding_user",
            "level",
            "owner_user_id",
            "target_kind",
            "target_stable_key",
            unique=True,
            postgresql_where=sa.text("level = 'user'"),
        ),
        sa.Index(
            "uq_runtime_binding_project",
            "level",
            "project_id",
            "target_kind",
            "target_stable_key",
            unique=True,
            postgresql_where=sa.text("level IN ('project_override', 'project_default')"),
        ),
        sa.Index(
            "uq_runtime_binding_studio",
            "level",
            "target_kind",
            "target_stable_key",
            unique=True,
            postgresql_where=sa.text("level = 'studio_default'"),
        ),
        sa.Index("ix_runtime_bindings_owner", "owner_user_id"),
        sa.Index("ix_runtime_bindings_project", "project_id"),
    )

    level: Mapped[str]
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), default=None
    )
    target_kind: Mapped[str]
    target_stable_key: Mapped[str]
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
