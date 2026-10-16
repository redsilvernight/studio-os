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
from uuid import UUID

from pydantic import Field

from studio_contracts.auth import CapabilityToken, MachineEligibility
from studio_contracts.common import ContractModel
from studio_contracts.roadmaps import RoadmapStatus


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
