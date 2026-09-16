from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate, TimestampedModel


class BuildStatus(StrEnum):
    """Build lifecycle, mirrored from the `build.*` event types. Transitions
    only ever move forward (`queued` -> `in_progress` -> `succeeded`/`failed`)
    and are written by the server (GitHub webhook, reconcile worker) — no
    client PATCH endpoint exists."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Build(TimestampedModel):
    """A CI build observed on a project's GitHub repository.
    Additive-only: new optional fields may appear, existing ones are never
    renamed or removed."""

    id: UUID
    project_id: UUID
    task_id: UUID | None = None
    github_integration_id: UUID | None = None
    workflow_run_id: int
    workflow_name: str
    run_number: int
    branch: str
    commit_sha: str
    pr_number: int | None = None
    status: BuildStatus = BuildStatus.QUEUED
    conclusion: str | None = None
    html_url: str
    actor_login: str
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GitHubIntegration(TimestampedModel):
    """Per-project GitHub wiring. At most one row per project in
    v1 (`project_id` unique) — the webhook secret itself is never stored
    here: it is a single process-wide env var (`STUDIO_GITHUB_WEBHOOK_SECRET`),
    never logged, never returned by the API."""

    id: UUID
    project_id: UUID
    repo_full_name: str
    default_branch: str = "main"
    enabled: bool = True
    created_by_user_id: UUID


class GitHubIntegrationCreate(IdempotentCreate):
    project_id: UUID
    repo_full_name: str
    default_branch: str | None = None
    enabled: bool | None = None


class GitHubIntegrationUpdate(ContractModel):
    repo_full_name: str | None = None
    default_branch: str | None = None
    enabled: bool | None = None


class ProducerJobKind(StrEnum):
    """What the Producer was asked to compute. Deterministic and
    model-agnostic in v1 — no LLM in the server core."""

    PRIORITY_ANALYSIS = "priority_analysis"
    BLOCKER_DETECTION = "blocker_detection"
    PARALLELIZATION = "parallelization"
    DECOMPOSITION = "decomposition"


class ProducerJobStatus(StrEnum):
    REQUESTED = "requested"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProducerJob(ContractModel):
    """A bounded, synchronous Producer computation over one project's shared
    state. The Producer never mutates `Task`/`ResourceClaim`:
    a `decomposition` result is a proposal — the caller creates the
    sub-tasks itself via `POST /tasks` (idempotent)."""

    id: UUID
    project_id: UUID
    kind: ProducerJobKind
    status: ProducerJobStatus = ProducerJobStatus.REQUESTED
    task_id: UUID | None = None
    result: dict[str, object] = {}
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ProducerJobRequest(IdempotentCreate):
    project_id: UUID
    kind: ProducerJobKind
    task_id: UUID | None = None


class GitHubWebhookResult(ContractModel):
    """Outcome of one verified GitHub delivery. `status` is `accepted`
    (events/builds written or converged) or `ignored` (unknown event,
    unconfigured repository, disabled integration) — both answer `200`/`202`
    at HTTP level, never `500`."""

    status: str
    github_event: str | None = None
    build_id: UUID | None = None
    pr_number: int | None = None
    detail: str | None = None
