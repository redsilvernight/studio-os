from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from studio_contracts.common import ContractModel


class EventType(StrEnum):
    """Fixed dotted names (`domain.verb`: task.created, session.ended, ...).
    Additive-only: new members may appear, existing ones are never renamed
    or removed — readers should tolerate unknown types."""

    PROJECT_CREATED = "project.created"

    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_UPDATED = "task.updated"
    TASK_BLOCKED = "task.blocked"
    TASK_COMPLETED = "task.completed"

    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"

    RESOURCE_CLAIMED = "resource.claimed"
    RESOURCE_RENEWED = "resource.renewed"
    RESOURCE_RELEASED = "resource.released"
    RESOURCE_CONFLICT = "resource.conflict"

    DECISION_PROPOSED = "decision.proposed"
    DECISION_CREATED = "decision.created"

    LIBRARY_VERSION_CREATED = "library.version.created"
    LIBRARY_VERSION_ACTIVATED = "library.version.activated"
    LIBRARY_RESOURCE_DEPRECATED = "library.resource.deprecated"
    LIBRARY_LOCK_SET = "library.lock.set"
    LIBRARY_LOCK_RELEASED = "library.lock.released"

    ROADMAP_CREATED = "roadmap.created"
    ROADMAP_UPDATED = "roadmap.updated"
    ROADMAP_PROPOSED = "roadmap.proposed"
    ROADMAP_APPROVED = "roadmap.approved"
    ROADMAP_CHANGES_REQUESTED = "roadmap.changes_requested"
    ROADMAP_REJECTED = "roadmap.rejected"
    ROADMAP_ACTIVATED = "roadmap.activated"
    ROADMAP_COMPLETED = "roadmap.completed"
    ROADMAP_ARCHIVED = "roadmap.archived"
    ROADMAP_HYDRATED = "roadmap.hydrated"

    AGENT_STARTED = "agent.started"
    AGENT_STOPPED = "agent.stopped"

    AI_WORK_STARTED = "ai_work.started"
    AI_WORK_COMPLETED = "ai_work.completed"
    AI_WORK_FAILED = "ai_work.failed"
    AI_WORK_REVIEW_REQUESTED = "ai_work.review_requested"
    AI_WORK_APPROVED = "ai_work.approved"
    AI_WORK_CHANGES_REQUESTED = "ai_work.changes_requested"

    GIT_COMMIT = "git.commit"
    GIT_BRANCH_CHANGED = "git.branch.changed"
    GIT_PR_OPENED = "git.pr.opened"
    GIT_PR_MERGED = "git.pr.merged"

    GRAPH_UPDATED = "graph.updated"
    MEMORY_PROPOSED = "memory.proposed"
    MEMORY_UPDATED = "memory.updated"

    GODOT_STARTED = "godot.started"
    GODOT_STOPPED = "godot.stopped"

    RECORDING_STARTED = "recording.started"
    RECORDING_FINISHED = "recording.finished"
    RECORDING_MARKER_CREATED = "recording.marker.created"

    BUILD_STARTED = "build.started"
    BUILD_SUCCEEDED = "build.succeeded"
    BUILD_FAILED = "build.failed"

    PRODUCER_JOB_REQUESTED = "producer.job.requested"
    PRODUCER_JOB_COMPLETED = "producer.job.completed"
    PRODUCER_JOB_FAILED = "producer.job.failed"

    TRANSFER_CREATED = "transfer.created"
    TRANSFER_UPLOADING = "transfer.uploading"
    TRANSFER_READY = "transfer.ready"
    TRANSFER_DOWNLOADED = "transfer.downloaded"
    TRANSFER_EXPIRED = "transfer.expired"
    TRANSFER_DELETED = "transfer.deleted"

    MARKETING_CANDIDATE_CREATED = "marketing.candidate.created"
    MARKETING_POST_PUBLISHED = "marketing.post.published"


ActorType = Literal["user", "agent", "system"]


class EventEnvelope(ContractModel):
    """Fixed envelope — only `payload` grows across `schema_version` bumps;
    every other field keeps its shape. Unknown event types or extra payload
    fields must be tolerated, never rejected."""

    event_id: UUID
    event_type: EventType
    project_id: UUID
    task_id: UUID | None = None
    machine_id: UUID | None = None
    actor_type: ActorType
    actor_id: UUID
    client_timestamp: datetime
    server_timestamp: datetime
    payload: dict[str, object] = {}
    schema_version: int = 1


class EventCreate(ContractModel):
    """POST /events request body. `event_id` is client-generated and stable
    across retries — it IS the idempotency key for events: replaying the
    same event_id returns the original stored event rather than creating a
    duplicate."""

    event_id: UUID
    event_type: EventType
    project_id: UUID
    task_id: UUID | None = None
    machine_id: UUID | None = None
    actor_type: ActorType
    actor_id: UUID
    client_timestamp: datetime
    payload: dict[str, object] = {}
    schema_version: int = 1
