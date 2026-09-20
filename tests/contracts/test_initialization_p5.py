from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from studio_contracts import initialization
from studio_contracts.initialization import (
    INITIALIZATION_FORMAT,
    MAX_INITIALIZATION_TASKS,
    InitializationAction,
    InitializationActionKind,
    InitializationBindingRef,
    InitializationProblemCode,
    InitializationProjectSpec,
    InitializationResourceRef,
    InitializationSection,
    InitializationTask,
    ProjectInitializationPlan,
    ProjectInitializationRequest,
    count_actions,
    initialization_plan_problems,
)
from studio_contracts.library import LibraryKind, LibraryScope
from studio_contracts.roadmaps import PhaseContent, RoadmapDocument, StepContent, TaskPlanItem

PLANS_FIXTURE = Path(__file__).with_name("initialization_plans.json")
FORBIDDEN_FIELD_NAMES = {"provider", "model", "harness", "agent_profile", "runtime_id"}


def _load_plans() -> list[dict[str, object]]:
    raw = json.loads(PLANS_FIXTURE.read_text(encoding="utf-8"))
    return list(raw)


def _minimal(**overrides: object) -> ProjectInitializationPlan:
    data: dict[str, object] = {
        "project": {"slug": "p", "name": "P"},
    }
    data.update(overrides)
    return ProjectInitializationPlan.model_validate(data)


def _roadmap(*steps: StepContent) -> RoadmapDocument:
    return RoadmapDocument(
        title="Plan", phases=[PhaseContent(key="P0", title="Phase", steps=list(steps))]
    )


def test_fixtures_are_valid_and_round_trip() -> None:
    plans = _load_plans()
    assert len(plans) == 3
    for raw in plans:
        plan = ProjectInitializationPlan.model_validate(raw)
        assert plan.format == INITIALIZATION_FORMAT
        assert initialization_plan_problems(plan) == []
        assert ProjectInitializationPlan.model_validate_json(plan.model_dump_json()) == plan


def test_project_alone_is_a_valid_plan_and_roadmap_is_optional() -> None:
    plan = _minimal()
    assert plan.roadmap is None
    assert plan.tasks == [] and plan.resources == [] and plan.bindings == []
    assert initialization_plan_problems(plan) == []
    assert count_actions([]).created == 0


def test_extra_fields_and_foreign_format_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ProjectInitializationPlan.model_validate(
            {"project": {"slug": "p", "name": "P"}, "provider": "anything"}
        )
    with pytest.raises(ValidationError):
        ProjectInitializationPlan.model_validate(
            {"format": "studio.initialization/v2", "project": {"slug": "p", "name": "P"}}
        )
    with pytest.raises(ValidationError):
        InitializationProjectSpec.model_validate({"slug": "p", "name": "P", "model": "x"})


def test_session_binding_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InitializationBindingRef.model_validate(
            {
                "level": "session",
                "target_kind": "agent_definition",
                "target_stable_key": "a",
                "target": {"harness_ref": "local"},
            }
        )


def test_duplicate_task_keys_are_reported() -> None:
    plan = _minimal(
        tasks=[
            {"key": "a", "title": "Un"},
            {"key": "a", "title": "Deux"},
        ]
    )
    problems = initialization_plan_problems(plan)
    assert [p.code for p in problems] == [InitializationProblemCode.DUPLICATE_TASK_KEY]
    assert problems[0].section is InitializationSection.TASKS
    assert problems[0].blocking is True


def test_task_referencing_a_step_needs_a_roadmap_and_a_known_key() -> None:
    without = _minimal(tasks=[{"key": "a", "title": "Un", "roadmap_step_key": "P0.1"}])
    assert [p.code for p in initialization_plan_problems(without)] == [
        InitializationProblemCode.ROADMAP_STEP_WITHOUT_ROADMAP
    ]

    unknown = _minimal(
        roadmap=_roadmap(StepContent(key="P0.1", title="s")),
        tasks=[{"key": "a", "title": "Un", "roadmap_step_key": "nope"}],
    )
    assert [p.code for p in initialization_plan_problems(unknown)] == [
        InitializationProblemCode.UNKNOWN_ROADMAP_STEP
    ]

    valid = _minimal(
        roadmap=_roadmap(StepContent(key="P0.1", title="s")),
        tasks=[{"key": "a", "title": "Un", "roadmap_step_key": "P0.1"}],
    )
    assert initialization_plan_problems(valid) == []


def test_invalid_roadmap_document_is_reported() -> None:
    cyclic = _roadmap(
        StepContent(key="a", title="a", depends_on=["b"]),
        StepContent(key="b", title="b", depends_on=["a"]),
    )
    problems = initialization_plan_problems(_minimal(roadmap=cyclic))
    assert [p.code for p in problems] == [InitializationProblemCode.INVALID_ROADMAP]
    assert problems[0].message == "dependency_cycle"


def test_duplicate_resource_and_binding_refs_are_reported() -> None:
    ref = {"kind": "skill", "stable_key": "s", "scope": "studio"}
    resources = _minimal(resources=[ref, dict(ref)])
    assert [p.code for p in initialization_plan_problems(resources)] == [
        InitializationProblemCode.DUPLICATE_RESOURCE_REF
    ]

    binding = {
        "level": "user",
        "target_kind": "agent_definition",
        "target_stable_key": "a",
        "target": {"harness_ref": "local"},
    }
    bindings = _minimal(bindings=[binding, dict(binding)])
    assert [p.code for p in initialization_plan_problems(bindings)] == [
        InitializationProblemCode.DUPLICATE_BINDING
    ]


def test_bounds_reject_oversized_plans() -> None:
    with pytest.raises(ValidationError):
        _minimal(
            tasks=[{"key": f"t{i}", "title": "t"} for i in range(MAX_INITIALIZATION_TASKS + 1)]
        )
    with pytest.raises(ValidationError):
        InitializationTask(key="a", title="x" * 201)


def test_count_actions_rolls_up_the_summary() -> None:
    actions = [
        InitializationAction(
            section=InitializationSection.PROJECT,
            key="p",
            action=InitializationActionKind.REUSE,
        ),
        InitializationAction(
            section=InitializationSection.TASKS, key="a", action=InitializationActionKind.CREATE
        ),
        InitializationAction(
            section=InitializationSection.TASKS, key="b", action=InitializationActionKind.CREATE
        ),
        InitializationAction(
            section=InitializationSection.ROADMAP,
            key="r",
            action=InitializationActionKind.SKIP,
        ),
    ]
    summary = count_actions(actions)
    assert (summary.created, summary.reused, summary.skipped) == (2, 1, 1)


def test_request_carries_a_plan_and_declared_provenance() -> None:
    request = ProjectInitializationRequest(plan=_minimal())
    assert request.provenance.agent_id is None
    assert request.plan.project.slug == "p"


def _all_models() -> list[type[BaseModel]]:
    return [
        obj
        for obj in vars(initialization).values()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == initialization.__name__
    ]


def test_domain_is_provider_model_harness_neutral() -> None:
    models = _all_models()
    assert models
    for model in models:
        assert not FORBIDDEN_FIELD_NAMES & set(model.model_fields), model.__name__


def test_resource_ref_keeps_scope_and_version_optional() -> None:
    ref = InitializationResourceRef(kind=LibraryKind.SKILL, stable_key="s")
    assert ref.scope is None and ref.version is None and ref.required is True
    assert (
        InitializationResourceRef(
            kind=LibraryKind.RULE, stable_key="r", scope=LibraryScope.PROJECT, version=2
        ).version
        == 2
    )
    with pytest.raises(ValidationError):
        InitializationResourceRef(kind=LibraryKind.SKILL, stable_key="s", version=0)


def test_task_plan_items_are_reused_from_the_neutral_roadmap_format() -> None:
    plan = _minimal(
        roadmap=_roadmap(
            StepContent(key="s", title="s", tasks=[TaskPlanItem(hydration_key="k", title="t")])
        )
    )
    assert plan.roadmap is not None
    assert plan.roadmap.phases[0].steps[0].tasks[0].hydration_key == "k"
    assert plan.roadmap.format == "studio.roadmap/v1"
