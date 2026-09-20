from __future__ import annotations

import itertools
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError
from studio_contracts import roadmaps
from studio_contracts.events import EventEnvelope, EventType
from studio_contracts.roadmaps import (
    ALLOWED_WRITES,
    KEY_PATTERN,
    MAX_CRITERIA,
    MAX_METADATA_KEYS,
    MAX_PHASES,
    ROADMAP_FORMAT,
    ROADMAP_TRANSITIONS,
    TRANSITIONS_REQUIRING_COMMENT,
    HydrationAction,
    HydrationApplyRequest,
    HydrationItem,
    HydrationRequest,
    HydrationResult,
    PhaseContent,
    ProposalReview,
    ReviewDecision,
    Roadmap,
    RoadmapDocument,
    RoadmapErrorCode,
    RoadmapErrorDetail,
    RoadmapOrigin,
    RoadmapStatus,
    RoadmapTransition,
    StepContent,
    StepProgressUpdate,
    StepState,
    StepStateOverride,
    TaskPlanItem,
    TaskStatusValue,
    TransitionRequest,
    WriteKind,
    WriteProvenance,
    compute_progress,
    count_hydration,
    derive_step_state,
    find_dependency_cycle,
    is_agent_write,
    roadmap_document_errors,
    transition_requires_provision,
    transition_target,
    waiting_on,
    write_allowed,
)

from tests.conftest import load_fixture

FORBIDDEN_FIELD_NAMES = {"provider", "model", "harness", "agent_profile", "runtime_id"}


def _doc(*steps: StepContent, phase: str = "P1") -> RoadmapDocument:
    return RoadmapDocument(
        title="t", phases=[PhaseContent(key=phase, title="p", steps=list(steps))]
    )


def _step(key: str, *deps: str, tasks: list[TaskPlanItem] | None = None) -> StepContent:
    return StepContent(key=key, title=key, depends_on=list(deps), tasks=tasks or [])


def test_transition_table_is_closed_and_archived_is_terminal() -> None:
    assert not any(source is RoadmapStatus.ARCHIVED for source, _ in ROADMAP_TRANSITIONS)
    for status, transition in itertools.product(RoadmapStatus, RoadmapTransition):
        assert transition_target(status, transition) is ROADMAP_TRANSITIONS.get(
            (status, transition)
        )


def test_every_status_is_reachable_from_draft() -> None:
    reachable = {RoadmapStatus.DRAFT}
    changed = True
    while changed:
        changed = False
        for (source, _), target in ROADMAP_TRANSITIONS.items():
            if source in reachable and target not in reachable:
                reachable.add(target)
                changed = True
    assert reachable == set(RoadmapStatus)


def test_only_draft_submit_and_draft_archive_are_writer_level() -> None:
    writer_level = {
        pair for pair in ROADMAP_TRANSITIONS if not transition_requires_provision(*pair)
    }
    assert writer_level == {
        (RoadmapStatus.DRAFT, RoadmapTransition.SUBMIT),
        (RoadmapStatus.DRAFT, RoadmapTransition.ARCHIVE),
    }


def test_approval_and_activation_require_provision() -> None:
    for pair in (
        (RoadmapStatus.PROPOSED, RoadmapTransition.APPROVE),
        (RoadmapStatus.DRAFT, RoadmapTransition.ACTIVATE),
        (RoadmapStatus.PROPOSED, RoadmapTransition.REJECT),
        (RoadmapStatus.ACTIVE, RoadmapTransition.ARCHIVE),
    ):
        assert transition_requires_provision(*pair)


def test_find_dependency_cycle_none_and_found() -> None:
    assert find_dependency_cycle({"a": [], "b": ["a"], "c": ["a", "b"]}) is None
    cycle = find_dependency_cycle({"a": ["b"], "b": ["c"], "c": ["a"], "d": []})
    assert cycle is not None
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}


def test_find_dependency_cycle_is_deterministic_and_handles_long_chains() -> None:
    edges = {f"s{i}": [f"s{i + 1}"] for i in range(5000)}
    edges["s5000"] = []
    assert find_dependency_cycle(edges) is None
    edges["s5000"] = ["s0"]
    first = find_dependency_cycle(edges)
    assert first is not None
    assert first == find_dependency_cycle(dict(reversed(edges.items())))


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        (_doc(_step("a"), _step("a")), "duplicate_step_key"),
        (_doc(_step("a", "zzz")), "unknown_dependency"),
        (_doc(_step("a", "a")), "self_dependency"),
        (_doc(_step("a", "b"), _step("b", "a")), "dependency_cycle"),
        (_doc(_step("a"), _step("b", "a", "a")), "duplicate_dependency"),
        (
            _doc(_step("a", tasks=[TaskPlanItem(hydration_key="k", title="x")] * 2)),
            "duplicate_hydration_key",
        ),
    ],
)
def test_document_semantic_errors(document: RoadmapDocument, reason: str) -> None:
    errors = roadmap_document_errors(document)
    assert [error["reason"] for error in errors] == [reason]
    assert errors[0]["field"]


def test_duplicate_phase_key_and_valid_document() -> None:
    phases = [PhaseContent(key="P", title="a"), PhaseContent(key="P", title="b")]
    errors = roadmap_document_errors(RoadmapDocument(title="t", phases=phases))
    assert errors[0]["reason"] == "duplicate_phase_key"
    assert roadmap_document_errors(_doc(_step("a"), _step("b", "a"))) == []


def test_cross_phase_dependency_is_allowed() -> None:
    document = RoadmapDocument(
        title="t",
        phases=[
            PhaseContent(key="A", title="a", steps=[_step("a1")]),
            PhaseContent(key="B", title="b", steps=[_step("b1", "a1")]),
        ],
    )
    assert roadmap_document_errors(document) == []


def test_schema_bounds_reject_oversized_payloads() -> None:
    with pytest.raises(ValidationError):
        RoadmapDocument(title="x" * 201)
    with pytest.raises(ValidationError):
        StepContent(key="a", title="t", acceptance_criteria=["c"] * (MAX_CRITERIA + 1))
    with pytest.raises(ValidationError):
        RoadmapDocument(title="t", metadata={f"k{i}": 1 for i in range(MAX_METADATA_KEYS + 1)})
    with pytest.raises(ValidationError):
        RoadmapDocument(
            title="t", phases=[PhaseContent(key=f"p{i}", title="t") for i in range(MAX_PHASES + 1)]
        )
    with pytest.raises(ValidationError):
        RoadmapDocument.model_validate({"title": "t", "metadata": {"nested": {"a": 1}}})


@pytest.mark.parametrize("key", ["", " a", "a b", "a/b", "../x", "é", "a" * 65, ".a", "-a"])
def test_keys_reject_unsafe_shapes(key: str) -> None:
    with pytest.raises(ValidationError):
        StepContent(key=key, title="t")


def test_keys_accept_plan_style_identifiers() -> None:
    for key in ("P0", "P0.1", "setup-db", "a_b"):
        assert StepContent(key=key, title="t").key == key
    assert KEY_PATTERN.startswith("^")


def test_extra_fields_and_foreign_format_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RoadmapDocument.model_validate({"title": "t", "provider": "anything"})
    with pytest.raises(ValidationError):
        RoadmapDocument.model_validate({"title": "t", "format": "studio.roadmap/v2"})
    assert RoadmapDocument(title="t").format == ROADMAP_FORMAT
    with pytest.raises(ValidationError):
        WriteProvenance.model_validate({"origin": "manual", "model": "x"})


def _all_models() -> list[type[BaseModel]]:
    return [
        obj
        for obj in vars(roadmaps).values()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == roadmaps.__name__
    ]


def test_domain_is_provider_model_harness_neutral() -> None:
    models = _all_models()
    assert models
    for model in models:
        assert not FORBIDDEN_FIELD_NAMES & set(model.model_fields), model.__name__


def test_no_roadmap_id_leaks_into_task_contract() -> None:
    from studio_contracts.tasks import Task, TaskCreate, TaskUpdate

    for model in (Task, TaskCreate, TaskUpdate):
        assert "roadmap_id" not in model.model_fields


def test_neutral_document_carries_no_ids_or_status() -> None:
    for model in (RoadmapDocument, PhaseContent, StepContent, TaskPlanItem):
        assert not {"id", "status", "task_id", "project_id", "provenance"} & set(model.model_fields)


@pytest.mark.parametrize(
    ("override", "statuses", "expected"),
    [
        (StepStateOverride.SKIPPED, [TaskStatusValue.COMPLETED], StepState.SKIPPED),
        (StepStateOverride.DONE, [], StepState.DONE),
        (None, [], StepState.NOT_STARTED),
        (None, [TaskStatusValue.COMPLETED, TaskStatusValue.COMPLETED], StepState.DONE),
        (None, [TaskStatusValue.COMPLETED, TaskStatusValue.CREATED], StepState.NOT_STARTED),
        (None, [TaskStatusValue.COMPLETED, TaskStatusValue.IN_PROGRESS], StepState.IN_PROGRESS),
        (None, [TaskStatusValue.IN_PROGRESS, TaskStatusValue.BLOCKED], StepState.BLOCKED),
    ],
)
def test_derive_step_state(
    override: StepStateOverride | None, statuses: list[TaskStatusValue], expected: StepState
) -> None:
    assert derive_step_state(override, statuses) is expected


def test_waiting_on_and_progress() -> None:
    states = {"a": StepState.DONE, "b": StepState.SKIPPED, "c": StepState.IN_PROGRESS}
    assert waiting_on(["c", "b", "a", "missing"], states) == ["c", "missing"]
    progress = compute_progress([StepState.DONE, StepState.SKIPPED, StepState.NOT_STARTED])
    assert (progress.done, progress.total, progress.skipped, progress.ratio) == (1, 2, 1, 0.5)
    assert compute_progress([]).ratio == 1.0
    assert compute_progress([StepState.SKIPPED]).ratio == 1.0


def test_count_hydration() -> None:
    items = [
        HydrationItem(step_key="a", hydration_key="k", action=action, title="t")
        for action in (
            HydrationAction.CREATE,
            HydrationAction.CREATE,
            HydrationAction.REUSE,
            HydrationAction.SKIP,
        )
    ]
    counts = count_hydration(items)
    assert (counts.create, counts.reuse, counts.skip) == (2, 1, 1)


def test_hydration_apply_requires_expected_version_preview_does_not() -> None:
    HydrationRequest()
    with pytest.raises(ValidationError):
        HydrationApplyRequest.model_validate({})
    assert HydrationApplyRequest(expected_version=3).step_keys is None
    with pytest.raises(ValidationError):
        HydrationRequest.model_validate({"expected_version": 1})


def test_agent_write_cannot_be_downgraded_by_declaring_manual() -> None:
    manual = WriteProvenance()
    assert not is_agent_write(False, manual)
    assert is_agent_write(True, manual)
    assert is_agent_write(False, WriteProvenance(agent_id=uuid4()))
    assert is_agent_write(False, WriteProvenance(origin=RoadmapOrigin.AI_PROPOSAL))
    assert is_agent_write(True, WriteProvenance(origin=RoadmapOrigin.MANUAL, agent_id=None))


def test_write_matrix_by_status() -> None:
    assert set(ALLOWED_WRITES) == set(RoadmapStatus)
    for status in (RoadmapStatus.PROPOSED, RoadmapStatus.COMPLETED, RoadmapStatus.ARCHIVED):
        assert not any(write_allowed(status, kind) for kind in WriteKind)
    assert write_allowed(RoadmapStatus.ACTIVE, WriteKind.HYDRATION_APPLY)
    assert write_allowed(RoadmapStatus.ACTIVE, WriteKind.PROPOSAL)
    assert not write_allowed(RoadmapStatus.DRAFT, WriteKind.HYDRATION_APPLY)
    assert not write_allowed(RoadmapStatus.DRAFT, WriteKind.PROPOSAL)


@pytest.mark.parametrize("transition", sorted(TRANSITIONS_REQUIRING_COMMENT))
def test_comment_is_required_for_transitions_that_need_one(
    transition: RoadmapTransition,
) -> None:
    with pytest.raises(ValidationError):
        TransitionRequest(transition=transition, expected_version=1)
    with pytest.raises(ValidationError):
        TransitionRequest(transition=transition, expected_version=1, comment="   ")
    assert TransitionRequest(transition=transition, expected_version=1, comment="why").comment
    assert TransitionRequest(transition=RoadmapTransition.APPROVE, expected_version=1)


def test_proposal_review_requires_comment_unless_approved() -> None:
    assert ProposalReview(decision=ReviewDecision.APPROVE, expected_version=1)
    for decision in (ReviewDecision.REJECT, ReviewDecision.REQUEST_CHANGES):
        with pytest.raises(ValidationError):
            ProposalReview(decision=decision, expected_version=1)


def test_progress_update_validation() -> None:
    assert StepProgressUpdate(criteria_checked=[0, 2]).criteria_checked == [0, 2]
    with pytest.raises(ValidationError):
        StepProgressUpdate(criteria_checked=[1, 1])
    with pytest.raises(ValidationError):
        StepProgressUpdate(criteria_checked=[MAX_CRITERIA])
    with pytest.raises(ValidationError):
        StepProgressUpdate(clear_state_override=True, state_override=StepStateOverride.DONE)


def test_error_detail_uses_closed_codes() -> None:
    detail = RoadmapErrorDetail(error_code=RoadmapErrorCode.DEPENDENCY_CYCLE, path=["a", "b", "a"])
    assert detail.model_dump(mode="json", exclude_none=True)["error_code"] == "dependency_cycle"
    with pytest.raises(ValidationError):
        RoadmapErrorDetail.model_validate({"error_code": "nope"})


def test_roadmap_event_types_are_additive_and_envelope_unchanged() -> None:
    names = {t.value for t in EventType if t.value.startswith("roadmap.")}
    assert names == {
        "roadmap.created",
        "roadmap.updated",
        "roadmap.proposed",
        "roadmap.approved",
        "roadmap.changes_requested",
        "roadmap.rejected",
        "roadmap.activated",
        "roadmap.completed",
        "roadmap.archived",
        "roadmap.hydrated",
    }
    existing = {t.value for t in EventType}
    assert {"project.created", "task.created", "library.lock.released"} <= existing
    assert "payload" in EventEnvelope.model_fields


def test_document_fixtures_are_valid_and_round_trip() -> None:
    for raw in load_fixture("roadmap_documents"):
        document = RoadmapDocument.model_validate(raw)
        assert roadmap_document_errors(document) == []
        assert RoadmapDocument.model_validate_json(document.model_dump_json()) == document


def test_dogfood_document_is_the_roadmaps_roadmap() -> None:
    dogfood = RoadmapDocument.model_validate(load_fixture("roadmap_documents")[1])
    assert [phase.key for phase in dogfood.phases] == [f"P{n}" for n in range(11)]
    deps = {step.key: step.depends_on for phase in dogfood.phases for step in phase.steps}
    assert deps["P0.main"] == []
    assert set(deps["P10.main"]) == {f"P{n}.main" for n in (2, 3, 4, 5, 6, 7, 8, 9)}
    assert all(step.tasks for phase in dogfood.phases for step in phase.steps)


def test_roadmap_fixture_derived_fields_match_the_single_derivation() -> None:
    roadmap = Roadmap.model_validate(load_fixture("roadmaps")[0])
    steps = [step for phase in roadmap.phases for step in phase.steps]
    states = {step.key: step.state for step in steps}
    for step in steps:
        assert step.waiting_on == waiting_on(step.depends_on, states)
        open_step = step.state not in (StepState.DONE, StepState.SKIPPED)
        assert step.available is (open_step and not step.waiting_on)
    assert roadmap.progress == compute_progress([step.state for step in steps])
    assert roadmap.current_step_key == next(step.key for step in steps if step.available)
    for phase in roadmap.phases:
        assert phase.progress == compute_progress([step.state for step in phase.steps])


def test_hydration_fixtures_counts_are_consistent() -> None:
    for raw in load_fixture("roadmap_hydration"):
        result = HydrationResult.model_validate(raw)
        assert result.counts == count_hydration(result.items)
        created = [item for item in result.items if item.action is HydrationAction.CREATE]
        assert all((item.task_id is not None) == result.applied for item in created)
