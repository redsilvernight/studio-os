from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from studio_contracts.admission import (
    AdmissionCandidate,
    AdmissionDryRun,
    AdmissionExclusion,
    AdmissionExclusionReason,
)
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
    launchable: list[AdmissionCandidate] = []
    excluded: list[AdmissionExclusion] = []
    steps_without_tasks: list[str] = []

    eligible_machines = [machine for machine in snapshot.machines if machine.eligible]
    eligible_ids = {machine.machine_id for machine in eligible_machines}

    for step in snapshot.steps:
        if step.state in (StepState.DONE, StepState.SKIPPED):
            continue
        if not step.tasks:
            steps_without_tasks.append(step.key)
            continue
        for task in step.tasks:
            reasons: list[AdmissionExclusionReason] = []
            waiting_on: list[str] = []
            if snapshot.roadmap_status is not RoadmapStatus.ACTIVE:
                reasons.append(AdmissionExclusionReason.ROADMAP_NOT_ACTIVE)
            if step.waiting_on:
                reasons.append(AdmissionExclusionReason.DEPENDENCY_PENDING)
                waiting_on = list(step.waiting_on)
            if task.status is None:
                reasons.append(AdmissionExclusionReason.TASK_DATA_MISSING)
            elif task.status is TaskStatusValue.COMPLETED:
                reasons.append(AdmissionExclusionReason.TASK_COMPLETED)
            elif task.status is TaskStatusValue.BLOCKED:
                reasons.append(AdmissionExclusionReason.TASK_BLOCKED)
            if task.review_pending:
                reasons.append(AdmissionExclusionReason.REVIEW_PENDING)
            if task.launch_active:
                reasons.append(AdmissionExclusionReason.LAUNCH_ACTIVE)

            candidates = list(eligible_machines)
            if task.claimed_by_machine_id is not None:
                if task.claimed_by_machine_id in eligible_ids:
                    candidates = [
                        machine
                        for machine in candidates
                        if machine.machine_id == task.claimed_by_machine_id
                    ]
                else:
                    reasons.append(AdmissionExclusionReason.TASK_CLAIMED_ELSEWHERE)
            remaining_ids = {machine.machine_id for machine in candidates}
            if task.live_claim_machine_ids - remaining_ids:
                reasons.append(AdmissionExclusionReason.CLAIMS_HELD_ELSEWHERE)
            if not candidates:
                reasons.append(AdmissionExclusionReason.NO_ELIGIBLE_MACHINE)

            if reasons:
                excluded.append(
                    AdmissionExclusion(
                        task_id=task.task_id,
                        step_key=step.key,
                        title=task.title,
                        reasons=reasons,
                        waiting_on=waiting_on,
                    )
                )
            else:
                launchable.append(
                    AdmissionCandidate(
                        task_id=task.task_id,
                        step_key=step.key,
                        title=task.title or "",
                        machine_ids=[machine.machine_id for machine in candidates],
                    )
                )

    return AdmissionDryRun(
        roadmap_id=snapshot.roadmap_id,
        project_id=snapshot.project_id,
        roadmap_status=snapshot.roadmap_status,
        roadmap_version=snapshot.roadmap_version,
        harness_id=snapshot.harness_id,
        launchable=launchable,
        excluded=excluded,
        steps_without_tasks=steps_without_tasks,
        machines=list(snapshot.machines),
        plan_digest=_plan_digest(snapshot, launchable, excluded, steps_without_tasks),
        evaluated_at=evaluated_at,
    )


def _plan_digest(
    snapshot: AdmissionSnapshot,
    launchable: list[AdmissionCandidate],
    excluded: list[AdmissionExclusion],
    steps_without_tasks: list[str],
) -> str:
    payload = {
        "roadmap_id": str(snapshot.roadmap_id),
        "roadmap_version": snapshot.roadmap_version,
        "roadmap_status": snapshot.roadmap_status.value,
        "harness_id": snapshot.harness_id,
        "launchable": [item.model_dump(mode="json") for item in launchable],
        "excluded": [item.model_dump(mode="json") for item in excluded],
        "steps_without_tasks": list(steps_without_tasks),
        "machines": [
            {
                "machine_id": str(machine.machine_id),
                "eligible": machine.eligible,
                "reasons": [reason.value for reason in machine.reasons],
            }
            for machine in snapshot.machines
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
