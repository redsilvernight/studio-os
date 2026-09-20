"""Pure P4 helpers: bounded compaction of roadmap reads (no database)."""

from __future__ import annotations

from studio_contracts.roadmaps import HydrationResult, Roadmap, Step
from studio_mcp.tools.roadmaps import (
    MAX_UPCOMING_STEPS,
    _bounded,
    _compact_hydration,
    _compact_step,
    _compact_summary,
    _current_position,
)

from tests.conftest import load_fixture


def _roadmap() -> Roadmap:
    return Roadmap.model_validate(load_fixture("roadmaps")[0])


def test_bounded_truncates_only_when_needed() -> None:
    assert _bounded(None, 10) == (None, False)
    assert _bounded("short", 10) == ("short", False)
    assert _bounded("0123456789abc", 4) == ("0123", True)


def test_compact_summary_is_bounded_and_keeps_the_position_key() -> None:
    from studio_contracts.roadmaps import RoadmapSummary

    roadmap = _roadmap()
    summary = RoadmapSummary.model_validate(
        roadmap.model_dump(exclude={"context", "metadata", "phases"})
    )
    compact = _compact_summary(summary, max_chars=4)
    assert compact["id"] == str(summary.id)
    assert compact["status"] == summary.status.value
    assert compact["current_step_key"] == summary.current_step_key
    assert compact["progress"] == summary.progress.model_dump(mode="json")
    assert len(compact["title"]) <= 4 or not compact["truncated"]


def test_compact_step_bounds_criteria_and_reports_tasks() -> None:
    roadmaps = load_fixture("roadmaps")
    assert roadmaps
    roadmap = _roadmap()
    step: Step = next(step for phase in roadmap.phases for step in phase.steps)
    step.acceptance_criteria = ["x" * 50, "short"]
    compact = _compact_step(step, max_chars=5)
    assert compact["key"] == step.key
    assert all(len(criteria) <= 5 for criteria in compact["acceptance_criteria"])
    assert compact["truncated"] is True
    assert compact["linked_task_ids"] == [str(task.task_id) for task in step.linked_tasks]


def test_current_position_matches_the_derived_current_step() -> None:
    roadmap = _roadmap()
    position = _current_position(roadmap, max_chars=200)
    assert position["current_step_key"] == roadmap.current_step_key
    assert position["roadmap_id"] == str(roadmap.id)
    if roadmap.current_step_key is not None:
        assert position["current_step"] is not None
        assert position["current_step"]["key"] == roadmap.current_step_key
    assert len(position["upcoming_steps"]) <= MAX_UPCOMING_STEPS
    assert all(step.key != roadmap.current_step_key for step in position["upcoming_steps"])


def test_compact_hydration_applies_the_limit_and_flags_omissions() -> None:
    result = HydrationResult.model_validate(load_fixture("roadmap_hydration")[0])
    body = _compact_hydration(result, limit=1)
    assert len(body["items"]) == 1
    assert body["omitted_for_budget"] == len(result.items) - 1
    assert body["counts"] == result.counts.model_dump(mode="json")
    full = _compact_hydration(result, limit=10)
    assert full["omitted_for_budget"] == 0
    assert {item["action"] for item in full["items"]} == {"create", "reuse", "skip"}
