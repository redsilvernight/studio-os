from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin


class GitHubIntegrationModel(UUIDPKMixin, TimestampMixin, Base):
    """Per-project GitHub wiring (DEC-0059). One row per project in v1 —
    the webhook secret itself is never stored here (process-wide env var
    `STUDIO_GITHUB_WEBHOOK_SECRET`)."""

    __tablename__ = "github_integrations"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), unique=True
    )
    repo_full_name: Mapped[str]
    default_branch: Mapped[str] = mapped_column(default="main")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))


class BuildModel(UUIDPKMixin, TimestampMixin, Base):
    """A CI build observed on a project's GitHub repository (DEC-0059).
    Written by the server only (GitHub webhook, reconcile worker) — status
    moves forward, never through a client PATCH. `(project_id,
    workflow_run_id)` is unique so a webhook redelivery and the reconcile
    worker upsert the same row instead of duplicating it."""

    __tablename__ = "builds"
    __table_args__ = (
        UniqueConstraint("project_id", "workflow_run_id", name="uq_builds_project_workflow_run"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), default=None
    )
    github_integration_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("github_integrations.id"), default=None
    )
    workflow_run_id: Mapped[int] = mapped_column(BigInteger())
    workflow_name: Mapped[str]
    run_number: Mapped[int]
    branch: Mapped[str]
    commit_sha: Mapped[str]
    pr_number: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="queued")
    conclusion: Mapped[str | None] = mapped_column(default=None)
    html_url: Mapped[str]
    actor_login: Mapped[str]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ProducerJobModel(UUIDPKMixin, Base):
    """A bounded, synchronous Producer computation (DEC-0059) — requested,
    computed, then `completed`/`failed` with a bounded result payload. Never
    mutated after completion; no `version` (append-only journal, same rule as
    `WorkSession`/`Decision`/`AIWorkLog` in TECH/05)."""

    __tablename__ = "producer_jobs"

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    kind: Mapped[str]
    status: Mapped[str] = mapped_column(default="requested")
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), default=None
    )
    result: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
