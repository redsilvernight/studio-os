"""Roadmap domain tables (Roadmaps P2, DEC-0084/DEC-0085, migration 0013).

A Roadmap is a project-scoped *plan* (Roadmap -> Phase -> Step). Tasks stay the
units of work and the only source of truth for work status: there is no
`roadmap_id` on `tasks`; the only join is `roadmap_step_task_links`. Step state
and progress are derived at read time and never persisted (only the manual
`state_override`). No harness/provider/model column exists here: an agent is
joinable through `agent_id` -> `agents` only (DEC-0084 §2.7).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from studio_api.db.models.base import Base, TimestampMixin, UUIDPKMixin, VersionMixin


class ProvenanceMixin:
    """Provenance of a plan object (DEC-0084 §7): `actor_type`/`actor_id` use
    the vocabulary of `Event`/`Decision`; `agent_id` is only ever an agent
    attached to the authenticated machine (checked by the service)."""

    origin: Mapped[str] = mapped_column(default="manual")
    actor_type: Mapped[str] = mapped_column(default="user")
    actor_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id"), default=None
    )
    machine_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("machines.id"), default=None
    )


class RoadmapModel(UUIDPKMixin, TimestampMixin, VersionMixin, ProvenanceMixin, Base):
    __tablename__ = "roadmaps"
    __table_args__ = (
        Index(
            "uq_roadmaps_one_active_per_project",
            "project_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    title: Mapped[str]
    objective: Mapped[str | None] = mapped_column(default=None)
    context: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="draft")
    # `metadata` is reserved by SQLAlchemy's declarative base; only the column
    # keeps the contract name.
    roadmap_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    revision_no: Mapped[int] = mapped_column(default=0)
    approved_revision_no: Mapped[int | None] = mapped_column(default=None)


class RoadmapPhaseModel(UUIDPKMixin, TimestampMixin, VersionMixin, ProvenanceMixin, Base):
    __tablename__ = "roadmap_phases"
    __table_args__ = (UniqueConstraint("roadmap_id", "key", name="uq_roadmap_phases_key"),)

    roadmap_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roadmaps.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str]
    position: Mapped[int]
    title: Mapped[str]
    objective: Mapped[str | None] = mapped_column(default=None)


class RoadmapStepModel(UUIDPKMixin, TimestampMixin, VersionMixin, ProvenanceMixin, Base):
    __tablename__ = "roadmap_steps"
    __table_args__ = (UniqueConstraint("roadmap_id", "key", name="uq_roadmap_steps_key"),)

    roadmap_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roadmaps.id", ondelete="CASCADE"), index=True
    )
    phase_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roadmap_phases.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str]
    position: Mapped[int]
    title: Mapped[str]
    objective: Mapped[str | None] = mapped_column(default=None)
    context: Mapped[str | None] = mapped_column(default=None)
    instructions: Mapped[str | None] = mapped_column(default=None)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSONB, default=list)
    criteria_checked: Mapped[list[int]] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(default=None)
    step_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    task_plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    state_override: Mapped[str | None] = mapped_column(default=None)
    state_override_reason: Mapped[str | None] = mapped_column(default=None)


class RoadmapStepDependencyModel(Base):
    """`step_id` depends on `depends_on_step_id`; both belong to `roadmap_id`
    (enforced by the service, DAG checked with `find_dependency_cycle`)."""

    __tablename__ = "roadmap_step_dependencies"
    __table_args__ = (
        CheckConstraint("step_id <> depends_on_step_id", name="ck_roadmap_dep_not_self"),
    )

    step_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roadmap_steps.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_step_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roadmap_steps.id", ondelete="CASCADE"), primary_key=True
    )
    roadmap_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roadmaps.id", ondelete="CASCADE"), index=True
    )


class RoadmapStepTaskLinkModel(UUIDPKMixin, ProvenanceMixin, Base):
    """N:M join Step <-> Task (same project). `hydration_key` is unique per
    step when set: it is what makes hydration replay-safe."""

    __tablename__ = "roadmap_step_task_links"
    __table_args__ = (
        UniqueConstraint("step_id", "task_id", name="uq_roadmap_link_step_task"),
        Index(
            "uq_roadmap_link_step_hydration_key",
            "step_id",
            "hydration_key",
            unique=True,
            postgresql_where=text("hydration_key IS NOT NULL"),
        ),
    )

    step_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roadmap_steps.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), index=True
    )
    hydration_key: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoadmapRevisionModel(UUIDPKMixin, ProvenanceMixin, Base):
    """Append-only history (DEC-0084 §6): `snapshot` = neutral document of an
    applied state, `proposal` = a document submitted for review, `review` =
    a review note. Never updated except a proposal's review fields."""

    __tablename__ = "roadmap_revisions"
    __table_args__ = (
        Index(
            "uq_roadmap_revision_no_per_kind",
            "roadmap_id",
            "revision_no",
            "kind",
            unique=True,
        ),
    )

    roadmap_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roadmaps.id", ondelete="CASCADE"), index=True
    )
    revision_no: Mapped[int]
    kind: Mapped[str]
    status: Mapped[str | None] = mapped_column(default=None)
    base_revision_no: Mapped[int | None] = mapped_column(default=None)
    summary: Mapped[str | None] = mapped_column(default=None)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), default=None
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    review_comment: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
