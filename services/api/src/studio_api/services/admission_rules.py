from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from studio_contracts.admission import AdmissionDryRun
from studio_contracts.auth import MachineEligibility
from studio_contracts.roadmaps import RoadmapStatus, StepState, TaskStatusValue


@dataclass(frozen=True)
class TaskFacts:
    task_id: uuid.UUID
    title: str | None
    status: TaskStatusValue | None
    claimed_by_machine_id: uuid.UUID | None
    launch_active: bool
    review_pending: bool
    live_claim_machine_ids: frozenset[uuid.UUID]


@dataclass(frozen=True)
class StepFacts:
    key: str
    state: StepState
    waiting_on: tuple[str, ...]
    tasks: tuple[TaskFacts, ...]


@dataclass(frozen=True)
class AdmissionSnapshot:
    roadmap_id: uuid.UUID
    project_id: uuid.UUID
    roadmap_status: RoadmapStatus
    roadmap_version: int
    harness_id: str | None
    steps: tuple[StepFacts, ...]
    machines: tuple[MachineEligibility, ...]


def compose_dry_run(snapshot: AdmissionSnapshot, *, evaluated_at: datetime) -> AdmissionDryRun:
    raise NotImplementedError
