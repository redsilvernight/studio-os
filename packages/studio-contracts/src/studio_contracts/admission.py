"""Roadmap admission dry-run contract (Mission Control P05, additive).

A dry-run is a read: it lists which linked tasks of a roadmap could be
launched now, on which of the caller's machines, and why every other task is
excluded. It creates no `TaskLaunch`, reserves nothing and changes no state.
The same server state always yields the same lists, the same reasons and the
same `plan_digest`; only `evaluated_at` moves.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from studio_contracts.auth import CapabilityToken, MachineEligibility
from studio_contracts.common import ContractModel
from studio_contracts.roadmaps import RoadmapStatus
from studio_contracts.task_launch import (
    LAUNCH_DEFAULT_TTL_SECONDS,
    LAUNCH_MAX_TTL_SECONDS,
    HarnessId,
    StableKey,
    TaskLaunch,
)


class AdmissionExclusionReason(StrEnum):
    """Deterministic, listed in this declaration order."""

    ROADMAP_NOT_ACTIVE = "roadmap_not_active"
    DEPENDENCY_PENDING = "dependency_pending"
    TASK_DATA_MISSING = "task_data_missing"
    TASK_COMPLETED = "task_completed"
    TASK_BLOCKED = "task_blocked"
    REVIEW_PENDING = "review_pending"
    LAUNCH_ACTIVE = "launch_active"
    TASK_CLAIMED_ELSEWHERE = "task_claimed_elsewhere"
    CLAIMS_HELD_ELSEWHERE = "claims_held_elsewhere"
    NO_ELIGIBLE_MACHINE = "no_eligible_machine"


class AdmissionCandidate(ContractModel):
    task_id: UUID
    step_key: str
    title: str
    machine_ids: list[UUID] = Field(min_length=1)


class AdmissionExclusion(ContractModel):
    task_id: UUID
    step_key: str
    title: str | None = None
    reasons: list[AdmissionExclusionReason] = Field(min_length=1)
    waiting_on: list[str] = Field(default_factory=list)


class AdmissionDryRun(ContractModel):
    roadmap_id: UUID
    project_id: UUID
    roadmap_status: RoadmapStatus
    roadmap_version: int
    harness_id: CapabilityToken | None = None
    launchable: list[AdmissionCandidate] = Field(default_factory=list)
    excluded: list[AdmissionExclusion] = Field(default_factory=list)
    steps_without_tasks: list[str] = Field(default_factory=list)
    machines: list[MachineEligibility] = Field(default_factory=list)
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluated_at: datetime


ADMISSION_BATCH_MAX_ITEMS = 50


class AdmissionBatchItem(ContractModel):
    task_id: UUID
    machine_id: UUID


class AdmissionBatchRequest(ContractModel):
    """Admit a whole batch or nothing. `plan_digest` is the digest of the
    dry-run the human confirmed: the server recomputes the plan under lock and
    refuses with `admission_plan_changed` if it moved. Launch options are
    shared by every item, as in `TaskLaunchCreate`."""

    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    harness_id: HarnessId
    items: list[AdmissionBatchItem] = Field(min_length=1, max_length=ADMISSION_BATCH_MAX_ITEMS)
    agent_stable_key: StableKey | None = None
    profile_key: StableKey | None = None
    expires_in_seconds: int = Field(
        default=LAUNCH_DEFAULT_TTL_SECONDS, ge=60, le=LAUNCH_MAX_TTL_SECONDS
    )


class AdmissionRefusalReason(StrEnum):
    """Per-item refusal of a batch whose plan is unchanged."""

    DUPLICATE_ITEM = "duplicate_item"
    NOT_LAUNCHABLE = "not_launchable"
    MACHINE_NOT_ELIGIBLE = "machine_not_eligible"
    BUDGET_REFUSED = "budget_refused"


class AdmissionRefusal(ContractModel):
    task_id: UUID
    machine_id: UUID
    reason: AdmissionRefusalReason
    exclusion_reasons: list[AdmissionExclusionReason] = Field(default_factory=list)
    budget: dict[str, Any] | None = None


class AdmissionBatchRefused(ContractModel):
    """`409` body: `admission_plan_changed` carries the fresh `plan`;
    `admission_refused` carries every item refusal. Nothing was created."""

    error_code: Literal["admission_plan_changed", "admission_refused"]
    plan: AdmissionDryRun | None = None
    refusals: list[AdmissionRefusal] = Field(default_factory=list)


class AdmissionBatchResult(ContractModel):
    roadmap_id: UUID
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    launches: list[TaskLaunch] = Field(min_length=1)
    admitted_at: datetime
