from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from studio_contracts.common import ContractModel


class ReviewQueueKind(StrEnum):
    """Additive-only, like `EventType` (.claude/rules/contracts.md) — a new
    kind may appear, an existing one is never renamed or removed."""

    AI_WORK_REVIEW = "ai_work_review"
    DECISION_PROPOSAL = "decision_proposal"
    RESOURCE_CONFLICT = "resource_conflict"
    BUILD_FAILURE = "build_failure"
    PR_READY = "pr_ready"
    ROADMAP_PROPOSAL = "roadmap_proposal"


class ReviewQueueAIWorkItem(ContractModel):
    kind: Literal[ReviewQueueKind.AI_WORK_REVIEW] = ReviewQueueKind.AI_WORK_REVIEW
    id: UUID
    project_id: UUID
    task_id: UUID | None = None
    title: str
    agent_id: UUID
    requested_at: datetime


class ReviewQueueDecisionItem(ContractModel):
    kind: Literal[ReviewQueueKind.DECISION_PROPOSAL] = ReviewQueueKind.DECISION_PROPOSAL
    id: UUID
    project_id: UUID | None = None
    task_id: UUID | None = None
    readable_id: str
    title: str
    proposed_by_type: str
    requested_at: datetime


class ReviewQueueConflictItem(ContractModel):
    """`id` is the `resource.conflict` event's `event_id` — not a persisted
    conflict row (none exists): a best-effort, time-windowed
    signal, not a resolvable state."""

    kind: Literal[ReviewQueueKind.RESOURCE_CONFLICT] = ReviewQueueKind.RESOURCE_CONFLICT
    id: UUID
    project_id: UUID
    task_id: UUID | None = None
    title: str
    resource_path: str
    requested_at: datetime


class ReviewQueueBuildItem(ContractModel):
    """`id` is the failed `Build`'s id — informational (no build transition
    endpoint exists), like `ReviewQueueConflictItem`. `requested_at` is when
    the build completed as failed."""

    kind: Literal[ReviewQueueKind.BUILD_FAILURE] = ReviewQueueKind.BUILD_FAILURE
    id: UUID
    project_id: UUID
    task_id: UUID | None = None
    title: str
    workflow_name: str
    branch: str
    commit_sha: str
    conclusion: str | None = None
    requested_at: datetime


class ReviewQueuePRItem(ContractModel):
    """`id` is the `git.pr.opened` event's `event_id` — a best-effort,
    time-windowed signal (a PR opened long ago with no `git.pr.merged` ages
    out of the window), not a resolvable state."""

    kind: Literal[ReviewQueueKind.PR_READY] = ReviewQueueKind.PR_READY
    id: UUID
    project_id: UUID
    task_id: UUID | None = None
    title: str
    pr_number: int
    head_branch: str
    base_branch: str
    requested_at: datetime


class ReviewQueueRoadmapProposalItem(ContractModel):
    """A roadmap change waiting on a human reviewer: either a whole roadmap
    submitted for its first validation (`scope=roadmap`, the roadmap is
    `proposed`) or a pending revision proposal against an already approved
    roadmap (`scope=revision`). Both are resolved on the Roadmap surface
    (`POST .../transitions` and `POST .../proposals/{n}/review`), not from this
    queue: it stays a read-only view. `id` is the roadmap id for `roadmap` scope
    and the revision id for `revision`."""

    kind: Literal[ReviewQueueKind.ROADMAP_PROPOSAL] = ReviewQueueKind.ROADMAP_PROPOSAL
    id: UUID
    project_id: UUID
    task_id: UUID | None = None
    roadmap_id: UUID
    title: str
    scope: Literal["roadmap", "revision"]
    status: str
    revision_no: int | None = None
    base_revision_no: int | None = None
    summary: str | None = None
    actor_type: str
    agent_id: UUID | None = None
    requested_at: datetime


ReviewQueueItem = Annotated[
    ReviewQueueAIWorkItem
    | ReviewQueueDecisionItem
    | ReviewQueueConflictItem
    | ReviewQueueBuildItem
    | ReviewQueuePRItem
    | ReviewQueueRoadmapProposalItem,
    Field(discriminator="kind"),
]


class ReviewQueue(ContractModel):
    """Items sorted by `requested_at` descending (newest first)."""

    items: list[ReviewQueueItem]
    generated_at: datetime
