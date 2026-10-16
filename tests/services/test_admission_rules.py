from __future__ import annotations

import uuid
from datetime import UTC, datetime

from studio_api.services.admission_rules import (
    AdmissionSnapshot,
    StepFacts,
    TaskFacts,
    compose_dry_run,
)
from studio_contracts.admission import (
    AdmissionCandidate,
    AdmissionExclusionReason,
)
from studio_contracts.auth import MachineEligibility, MachineStatus
from studio_contracts.roadmaps import RoadmapStatus, StepState, TaskStatusValue

EVALUATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _machine(machine_id: uuid.UUID, *, eligible: bool = True) -> MachineEligibility:
    return MachineEligibility(
        machine_id=machine_id,
        display_name=f"machine-{machine_id.hex[:8]}",
        status=MachineStatus.ONLINE,
        eligible=eligible,
    )


def _task(
    *,
    status: TaskStatusValue | None = TaskStatusValue.CREATED,
    claimed_by_machine_id: uuid.UUID | None = None,
    launch_active: bool = False,
    review_pending: bool = False,
    live_claim_machine_ids: frozenset[uuid.UUID] = frozenset(),
    title: str | None = "Task",
) -> TaskFacts:
    return TaskFacts(
        task_id=uuid.uuid4(),
        title=title,
        status=status,
        claimed_by_machine_id=claimed_by_machine_id,
        launch_active=launch_active,
        review_pending=review_pending,
        live_claim_machine_ids=live_claim_machine_ids,
    )


def _step(
    key: str,
    *,
    state: StepState = StepState.NOT_STARTED,
    waiting_on: tuple[str, ...] = (),
    tasks: tuple[TaskFacts, ...] = (),
) -> StepFacts:
    return StepFacts(key=key, state=state, waiting_on=waiting_on, tasks=tasks)


def _snapshot(
    *,
    status: RoadmapStatus = RoadmapStatus.ACTIVE,
    steps: tuple[StepFacts, ...] = (),
    machines: tuple[MachineEligibility, ...] = (),
) -> AdmissionSnapshot:
    return AdmissionSnapshot(
        roadmap_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        roadmap_status=status,
        roadmap_version=3,
        harness_id="claude-code",
        steps=steps,
        machines=machines,
    )


def test_deterministic_same_snapshot_same_output_and_digest() -> None:
    machine = uuid.uuid4()
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(),)),),
        machines=(_machine(machine),),
    )

    first = compose_dry_run(snapshot, evaluated_at=datetime(2026, 1, 1, tzinfo=UTC))
    second = compose_dry_run(snapshot, evaluated_at=datetime(2026, 6, 30, tzinfo=UTC))

    assert first.plan_digest == second.plan_digest
    assert first.model_dump(exclude={"evaluated_at"}) == second.model_dump(exclude={"evaluated_at"})
    assert first.launchable == [
        AdmissionCandidate(
            task_id=snapshot.steps[0].tasks[0].task_id,
            step_key="s1",
            title="Task",
            machine_ids=[machine],
        )
    ]
    assert first.machines == [snapshot.machines[0]]


def test_digest_changes_when_a_fact_changes() -> None:
    machine = uuid.uuid4()
    base = _snapshot(steps=(_step("s1", tasks=(_task(),)),), machines=(_machine(machine),))
    other = _snapshot(
        status=RoadmapStatus.DRAFT,
        steps=(_step("s1", tasks=(_task(),)),),
        machines=(_machine(machine),),
    )

    assert (
        compose_dry_run(base, evaluated_at=EVALUATED_AT).plan_digest
        != compose_dry_run(other, evaluated_at=EVALUATED_AT).plan_digest
    )


def test_waiting_dependency_is_excluded_and_copies_waiting_on() -> None:
    snapshot = _snapshot(
        steps=(_step("s2", waiting_on=("s1",), tasks=(_task(),)),),
        machines=(_machine(uuid.uuid4()),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.launchable == []
    assert result.excluded[0].reasons == [AdmissionExclusionReason.DEPENDENCY_PENDING]
    assert result.excluded[0].waiting_on == ["s1"]


def test_review_pending_is_excluded() -> None:
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(review_pending=True),)),),
        machines=(_machine(uuid.uuid4()),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.excluded[0].reasons == [AdmissionExclusionReason.REVIEW_PENDING]


def test_active_launch_is_excluded() -> None:
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(launch_active=True),)),),
        machines=(_machine(uuid.uuid4()),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.excluded[0].reasons == [AdmissionExclusionReason.LAUNCH_ACTIVE]


def test_task_claimed_on_unknown_machine_is_excluded() -> None:
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(claimed_by_machine_id=uuid.uuid4()),)),),
        machines=(_machine(uuid.uuid4()),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.launchable == []
    assert result.excluded[0].reasons == [AdmissionExclusionReason.TASK_CLAIMED_ELSEWHERE]


def test_task_claimed_on_eligible_machine_restricts_candidates() -> None:
    claimed = uuid.uuid4()
    other = uuid.uuid4()
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(claimed_by_machine_id=claimed),)),),
        machines=(_machine(claimed), _machine(other)),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.excluded == []
    assert result.launchable[0].machine_ids == [claimed]


def test_absent_live_claims_leave_a_candidate() -> None:
    machine = uuid.uuid4()
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(live_claim_machine_ids=frozenset()),)),),
        machines=(_machine(machine),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.excluded == []
    assert result.launchable[0].machine_ids == [machine]


def test_live_claim_held_outside_eligible_machines_is_excluded() -> None:
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(live_claim_machine_ids=frozenset({uuid.uuid4()})),)),),
        machines=(_machine(uuid.uuid4()),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.excluded[0].reasons == [AdmissionExclusionReason.CLAIMS_HELD_ELSEWHERE]


def test_missing_task_data_is_excluded() -> None:
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(status=None, title=None),)),),
        machines=(_machine(uuid.uuid4()),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.excluded[0].reasons == [AdmissionExclusionReason.TASK_DATA_MISSING]


def test_step_without_tasks_is_listed_and_never_a_candidate() -> None:
    snapshot = _snapshot(
        steps=(
            _step("empty"),
            _step("done", state=StepState.DONE),
            _step("skipped", state=StepState.SKIPPED),
        ),
        machines=(_machine(uuid.uuid4()),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.steps_without_tasks == ["empty"]
    assert result.launchable == []
    assert result.excluded == []


def test_inactive_roadmap_excludes_every_task() -> None:
    snapshot = _snapshot(
        status=RoadmapStatus.DRAFT,
        steps=(_step("s1", tasks=(_task(), _task())),),
        machines=(_machine(uuid.uuid4()),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.launchable == []
    assert [item.reasons for item in result.excluded] == [
        [AdmissionExclusionReason.ROADMAP_NOT_ACTIVE],
        [AdmissionExclusionReason.ROADMAP_NOT_ACTIVE],
    ]


def test_no_eligible_machine_is_excluded() -> None:
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(),)),),
        machines=(_machine(uuid.uuid4(), eligible=False),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.excluded[0].reasons == [AdmissionExclusionReason.NO_ELIGIBLE_MACHINE]


def test_reasons_follow_declaration_order() -> None:
    snapshot = _snapshot(
        status=RoadmapStatus.DRAFT,
        steps=(
            _step(
                "s2",
                waiting_on=("s1",),
                tasks=(
                    _task(
                        status=TaskStatusValue.COMPLETED,
                        review_pending=True,
                        launch_active=True,
                    ),
                ),
            ),
        ),
        machines=(_machine(uuid.uuid4(), eligible=False),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.excluded[0].reasons == [
        AdmissionExclusionReason.ROADMAP_NOT_ACTIVE,
        AdmissionExclusionReason.DEPENDENCY_PENDING,
        AdmissionExclusionReason.TASK_COMPLETED,
        AdmissionExclusionReason.REVIEW_PENDING,
        AdmissionExclusionReason.LAUNCH_ACTIVE,
        AdmissionExclusionReason.NO_ELIGIBLE_MACHINE,
    ]


def test_machine_reasons_follow_declaration_order() -> None:
    snapshot = _snapshot(
        steps=(
            _step(
                "s1",
                tasks=(
                    _task(
                        claimed_by_machine_id=uuid.uuid4(),
                        live_claim_machine_ids=frozenset({uuid.uuid4()}),
                    ),
                ),
            ),
        ),
        machines=(_machine(uuid.uuid4(), eligible=False),),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.excluded[0].reasons == [
        AdmissionExclusionReason.TASK_CLAIMED_ELSEWHERE,
        AdmissionExclusionReason.CLAIMS_HELD_ELSEWHERE,
        AdmissionExclusionReason.NO_ELIGIBLE_MACHINE,
    ]


def test_eligible_machine_order_is_preserved() -> None:
    first = uuid.uuid4()
    hidden = uuid.uuid4()
    second = uuid.uuid4()
    snapshot = _snapshot(
        steps=(_step("s1", tasks=(_task(),)),),
        machines=(_machine(first), _machine(hidden, eligible=False), _machine(second)),
    )

    result = compose_dry_run(snapshot, evaluated_at=EVALUATED_AT)

    assert result.launchable[0].machine_ids == [first, second]
    assert [machine.machine_id for machine in result.machines] == [first, hidden, second]
