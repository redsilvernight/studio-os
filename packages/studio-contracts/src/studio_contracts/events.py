from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from studio_contracts.common import ContractModel


class EventType(StrEnum):
    """Fixed set per TECH/03_EVENT_CONTRACT.md. Additive-only (new members are a
    minor addition, never a rename/removal — see .claude/rules/contracts.md)."""

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

    AGENT_STARTED = "agent.started"
    AGENT_STOPPED = "agent.stopped"

    AI_WORK_STARTED = "ai_work.started"
    AI_WORK_COMPLETED = "ai_work.completed"
    AI_WORK_FAILED = "ai_work.failed"
    AI_WORK_REVIEW_REQUESTED = "ai_work.review_requested"

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
    """Fixed envelope per TECH/03_EVENT_CONTRACT.md — only `payload` grows across
    schema_version bumps; every other field is frozen shape."""

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
    across retries (TECH/04_AUTH_SYNC_CONTRACT.md, TECH/08_OFFLINE_SYNC.md) —
    it IS the idempotency key for events: replaying the same event_id returns
    the original stored event rather than creating a duplicate."""

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
