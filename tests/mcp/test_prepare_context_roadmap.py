"""Roadmaps P6 (DEC-0088): the Roadmap section of `studio_prepare_context`.

Every case goes through the real MCP tool, the real Roadmap services and a real
Postgres, exactly like `test_prepare_context.py`."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.project import ProjectModel
from studio_api.services import project_context_roadmap as roadmap_section
from studio_api.services import roadmaps
from studio_api.services.authz import Principal
from studio_contracts.library import LibraryKind
from studio_contracts.roadmaps import (
    ContextStep,
    Roadmap,
    RoadmapContext,
    RoadmapImport,
    RoadmapStatus,
    RoadmapTransition,
    StepProgressUpdate,
    StepStateOverride,
    TransitionRequest,
)
from studio_mcp.tools.context import studio_prepare_context

from tests.mcp.conftest import FakeContext
from tests.mcp.test_prepare_context import (
    Machine,
    _decision,
    _library,
    _principal,
    _project,
    _task,
    dump,
)

# --- builders ---------------------------------------------------------------------


def _step(key: str, **fields: Any) -> dict[str, Any]:
    return {"key": key, "title": fields.pop("title", f"Step {key}"), **fields}


def _doc(*phases: tuple[str, list[dict[str, Any]]], **top: Any) -> dict[str, Any]:
    return {
        "format": "studio.roadmap/v1",
        "title": top.pop("title", "Plan"),
        "phases": [{"key": key, "title": f"Phase {key}", "steps": steps} for key, steps in phases],
        **top,
    }


async def _import(
    db_session: AsyncSession,
    principal: Principal,
    project: ProjectModel,
    document: dict[str, Any],
    *,
    to: RoadmapStatus = RoadmapStatus.ACTIVE,
) -> Roadmap:
    """Import a document and walk it to the requested lifecycle status."""
    roadmap = await roadmaps.import_roadmap(
        db_session,
        principal,
        RoadmapImport(
            project_id=project.id,
            document=document,  # type: ignore[arg-type]
            submit=to is RoadmapStatus.PROPOSED,
        ),
    )
    if to in (RoadmapStatus.ACTIVE, RoadmapStatus.COMPLETED):
        roadmap = await _transition(db_session, principal, roadmap, RoadmapTransition.ACTIVATE)
    if to is RoadmapStatus.COMPLETED:
        roadmap = await _transition(db_session, principal, roadmap, RoadmapTransition.COMPLETE)
    if to is RoadmapStatus.ARCHIVED:
        roadmap = await _transition(db_session, principal, roadmap, RoadmapTransition.ARCHIVE)
    return roadmap


async def _transition(
    db_session: AsyncSession, principal: Principal, roadmap: Roadmap, transition: RoadmapTransition
) -> Roadmap:
    return await roadmaps.transition_roadmap(
        db_session,
        principal,
        roadmap.id,
        TransitionRequest(transition=transition, expected_version=roadmap.version),
    )


async def _progress(
    db_session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    key: str,
    **fields: Any,
) -> Roadmap:
    current = await roadmaps.get_roadmap(db_session, principal, roadmap_id)
    step = next(s for p in current.phases for s in p.steps if s.key == key)
    return await roadmaps.update_step_progress(
        db_session, principal, roadmap_id, key, StepProgressUpdate(**fields), step.version
    )


async def _done(
    db_session: AsyncSession, principal: Principal, roadmap_id: uuid.UUID, *keys: str
) -> None:
    for key in keys:
        await _progress(
            db_session, principal, roadmap_id, key, state_override=StepStateOverride.DONE
        )


async def _prepare(ctx: FakeContext, project: ProjectModel, objective: str, **kwargs: Any):
    return dump(await studio_prepare_context(str(project.id), objective, ctx, **kwargs))


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [k, *_all_strings(v)]]
    if isinstance(value, list):
        return [s for v in value for s in _all_strings(v)]
    return [value] if isinstance(value, str) else []


CHAIN = _doc(
    (
        "P",
        [
            _step("a", objective="Build the base", acceptance_criteria=["base works"]),
            _step("b", depends_on=["a"], acceptance_criteria=["b one", "b two"]),
            _step("c", depends_on=["b"]),
            _step("d"),
        ],
    ),
    objective="Ship it",
)


# --- absence and lifecycle statuses -------------------------------------------------


async def test_project_without_roadmap_is_unchanged(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    project = await _project(db_session)
    payload = await _prepare(auth_ctx, project, "anything about the project")
    for absent in ("roadmap", "roadmap_overview", "unavailable"):
        assert absent not in payload
    assert "roadmap" not in payload["returned"]
    assert not any(key.startswith("roadmap") for key in payload["additional_available"])
    assert not any(key.startswith("roadmap") for key in payload["omitted_for_budget"])
    assert "roadmap_scan_capped" not in payload["limits"]


async def test_draft_roadmap_is_only_an_overview(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    draft = await _import(db_session, principal, project, CHAIN, to=RoadmapStatus.DRAFT)
    payload = await _prepare(auth_ctx, project, "work on the plan")
    assert "roadmap" not in payload and "unavailable" not in payload
    overview = payload["roadmap_overview"]
    assert overview["counts"] == {"draft": 1}
    assert overview["draft_pending"] == 1
    assert [(r["id"], r["status"]) for r in overview["others"]] == [(str(draft.id), "draft")]


async def test_proposed_roadmap_is_only_an_overview(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _import(db_session, principal, project, CHAIN, to=RoadmapStatus.PROPOSED)
    payload = await _prepare(auth_ctx, project, "work on the plan")
    assert "roadmap" not in payload
    assert payload["roadmap_overview"]["counts"] == {"proposed": 1}
    assert payload["roadmap_overview"]["draft_pending"] == 1


async def test_active_roadmap_carries_status_progress_and_position(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    roadmap = await _import(db_session, principal, project, CHAIN)
    payload = await _prepare(auth_ctx, project, "work on the plan")
    section = payload["roadmap"]
    assert section["roadmap_id"] == str(roadmap.id)
    assert (section["title"], section["status"]) == ("Plan", "active")
    assert section["progress"] == {"done": 0, "total": 4, "skipped": 0, "ratio": 0.0}
    assert section["current_phase_key"] == "P"
    assert section["current_step"]["key"] == "a"
    assert section["why"] == {"reason": "active_roadmap", "matched_terms": []}
    assert payload["returned"]["roadmap"] == 1
    assert "roadmap_overview" not in payload  # the active roadmap is the only one


async def test_completed_roadmap_is_only_an_overview(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    document = _doc(("P", [_step("only")]))
    roadmap = await _import(db_session, principal, project, document)
    await _done(db_session, principal, roadmap.id, "only")
    roadmap = await roadmaps.get_roadmap(db_session, principal, roadmap.id)
    await _transition(db_session, principal, roadmap, RoadmapTransition.COMPLETE)
    payload = await _prepare(auth_ctx, project, "what is left")
    assert "roadmap" not in payload
    ref = payload["roadmap_overview"]["others"][0]
    assert (ref["status"], ref["progress"]["ratio"]) == ("completed", 1.0)
    assert payload["roadmap_overview"]["draft_pending"] == 0


async def test_archived_roadmap_is_ignored_and_pending_drafts_are_counted(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _import(db_session, principal, project, CHAIN, to=RoadmapStatus.ARCHIVED)
    await _import(
        db_session,
        principal,
        project,
        _doc(("P", [_step("x")]), title="Next"),
        to=RoadmapStatus.DRAFT,
    )
    await _import(db_session, principal, project, CHAIN)
    payload = await _prepare(auth_ctx, project, "work on the plan")
    assert payload["roadmap"]["draft_pending"] == 1
    assert payload["roadmap_overview"]["counts"] == {"active": 1, "draft": 1}
    assert [r["title"] for r in payload["roadmap_overview"]["others"]] == ["Next"]


async def test_only_the_active_roadmap_is_selected_among_roadmaps_of_every_status(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    other = await _project(db_session)
    await _import(db_session, principal, other, _doc(("P", [_step("z")]), title="Elsewhere"))

    finished = await _import(
        db_session, principal, project, _doc(("P", [_step("only")]), title="Finished")
    )
    await _done(db_session, principal, finished.id, "only")
    await _transition(
        db_session,
        principal,
        await roadmaps.get_roadmap(db_session, principal, finished.id),
        RoadmapTransition.COMPLETE,
    )
    await _import(
        db_session,
        principal,
        project,
        _doc(("P", [_step("o")]), title="Old"),
        to=RoadmapStatus.ARCHIVED,
    )
    await _import(
        db_session,
        principal,
        project,
        _doc(("P", [_step("p")]), title="Pitched"),
        to=RoadmapStatus.PROPOSED,
    )
    await _import(
        db_session,
        principal,
        project,
        _doc(("P", [_step("n")]), title="Next"),
        to=RoadmapStatus.DRAFT,
    )
    current = await _import(db_session, principal, project, CHAIN)

    payload = await _prepare(auth_ctx, project, "work on the plan")

    assert payload["roadmap"]["roadmap_id"] == str(current.id)
    assert (payload["roadmap"]["title"], payload["roadmap"]["status"]) == ("Plan", "active")
    assert payload["roadmap"]["draft_pending"] == 2
    overview = payload["roadmap_overview"]
    assert overview["counts"] == {"active": 1, "completed": 1, "draft": 1, "proposed": 1}
    assert overview["draft_pending"] == 2
    others = {(r["title"], r["status"]) for r in overview["others"]}
    assert others == {("Finished", "completed"), ("Pitched", "proposed"), ("Next", "draft")}
    assert str(current.id) not in {r["id"] for r in overview["others"]}
    assert "Old" not in _all_strings(payload["roadmap_overview"])
    assert "Elsewhere" not in _all_strings(payload)


async def test_without_an_active_roadmap_no_other_status_is_promoted_to_the_context(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    finished = await _import(db_session, principal, project, _doc(("P", [_step("only")])))
    await _done(db_session, principal, finished.id, "only")
    await _transition(
        db_session,
        principal,
        await roadmaps.get_roadmap(db_session, principal, finished.id),
        RoadmapTransition.COMPLETE,
    )
    await _import(db_session, principal, project, CHAIN, to=RoadmapStatus.PROPOSED)
    await _import(db_session, principal, project, CHAIN, to=RoadmapStatus.DRAFT)

    payload = await _prepare(auth_ctx, project, "work on the plan")

    assert "roadmap" not in payload and "unavailable" not in payload
    overview = payload["roadmap_overview"]
    assert overview["counts"] == {"completed": 1, "draft": 1, "proposed": 1}
    assert overview["draft_pending"] == 2
    assert sorted(r["status"] for r in overview["others"]) == ["completed", "draft", "proposed"]


async def test_roadmap_of_another_project_never_leaks(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    mine, other = await _project(db_session), await _project(db_session)
    await _import(db_session, principal, other, CHAIN)
    payload = await _prepare(auth_ctx, mine, "work on the plan")
    assert "roadmap" not in payload and "roadmap_overview" not in payload


# --- current step, available steps, blockers ---------------------------------------


async def test_current_step_is_the_first_available_and_upcoming_are_the_others(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    roadmap = await _import(db_session, principal, project, CHAIN)
    payload = await _prepare(auth_ctx, project, "plan")
    section = payload["roadmap"]
    assert section["current_step"]["key"] == "a"
    assert [s["key"] for s in section["upcoming_steps"]] == ["d"]  # b, c wait on a chain

    await _done(db_session, principal, roadmap.id, "a")
    section = (await _prepare(auth_ctx, project, "plan"))["roadmap"]
    assert section["current_step"]["key"] == "b"
    assert section["progress"]["done"] == 1
    assert [s["key"] for s in section["upcoming_steps"]] == ["d"]


async def test_blockers_are_unmet_dependencies_not_the_work_itself(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _import(db_session, principal, project, CHAIN)
    section = (await _prepare(auth_ctx, project, "plan"))["roadmap"]
    # `a` is available (the current step), `b` waits on it, `c` on `b`.
    assert section["blocking"] == ["b"]
    assert section["current_step"]["waiting_on"] == []


async def test_a_step_whose_task_is_blocked_is_reported_as_blocking(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    roadmap = await _import(db_session, principal, project, _doc(("P", [_step("a"), _step("b")])))
    task = await _task(db_session, principal, project, "Stuck work")
    await roadmaps.link_task_by_step_key(db_session, principal, roadmap.id, "a", task.id)
    task.status = "blocked"
    await db_session.commit()
    section = (await _prepare(auth_ctx, project, "plan"))["roadmap"]
    assert section["current_step"]["state"] == "blocked"
    assert section["blocking"] == ["a"]


# --- linked Tasks, criteria --------------------------------------------------------


async def test_linked_tasks_are_referenced_when_already_in_the_package_and_summarised_otherwise(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    roadmap = await _import(db_session, principal, project, CHAIN)
    requested = await _task(db_session, principal, project, "Requested work")
    related = await _task(db_session, principal, project, "Base foundations work")
    apart = await _task(db_session, principal, project, "Unrelated chore", "zzz")
    for task in (requested, related, apart):
        await roadmaps.link_task_by_step_key(db_session, principal, roadmap.id, "a", task.id)

    payload = await _prepare(
        auth_ctx, project, "base foundations", task_id=str(requested.id), limit=5
    )
    linked = {t["id"]: t for t in payload["roadmap"]["current_step"]["linked_tasks"]}
    assert linked[str(requested.id)] == {
        "id": str(requested.id),
        "title": None,
        "status": None,
        "in_context": "task",
    }
    assert linked[str(related.id)]["in_context"] == "related_tasks"
    assert linked[str(related.id)]["title"] is None  # no copy of what is already there
    assert linked[str(apart.id)]["title"] == "Unrelated chore"
    assert linked[str(apart.id)]["in_context"] is None
    assert payload["roadmap"]["current_step"]["linked_task_ids"] == [
        str(t.id) for t in sorted((requested, related, apart), key=lambda t: str(t.id))
    ]
    assert payload["task"]["id"] == str(requested.id)


async def test_the_step_of_the_requested_task_is_shown_when_it_is_not_the_current_one(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    roadmap = await _import(db_session, principal, project, CHAIN)
    task = await _task(db_session, principal, project, "Work for b")
    await roadmaps.link_task_by_step_key(db_session, principal, roadmap.id, "b", task.id)
    section = (await _prepare(auth_ctx, project, "plan", task_id=str(task.id)))["roadmap"]
    assert section["current_step"]["key"] == "a"
    assert section["task_step"]["key"] == "b"
    assert section["task_step"]["acceptance_criteria"] == ["b one", "b two"]
    assert section["task_step"]["waiting_on"] == ["a"]


async def test_only_criteria_still_to_satisfy_are_listed(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    document = _doc(("P", [_step("a", acceptance_criteria=["one", "two", "three"])]))
    roadmap = await _import(db_session, principal, project, document)
    await _progress(db_session, principal, roadmap.id, "a", criteria_checked=[1])
    step = (await _prepare(auth_ctx, project, "plan"))["roadmap"]["current_step"]
    assert step["acceptance_criteria"] == ["one", "three"]
    assert (step["criteria_total"], step["criteria_checked"]) == (3, 1)


async def test_a_dangling_or_missing_task_is_partial_data_not_a_failure(
    db_session: AsyncSession,
    machine: Machine,
    auth_ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    roadmap = await _import(db_session, principal, project, CHAIN)
    task = await _task(db_session, principal, project, "Gone soon")
    await roadmaps.link_task_by_step_key(db_session, principal, roadmap.id, "a", task.id)

    async def gone(_session: AsyncSession, _task_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(roadmap_section.tasks_service, "get_task", gone)
    payload = await _prepare(auth_ctx, project, "plan")
    assert payload["roadmap"]["current_step"]["linked_tasks"] == []
    assert payload["roadmap"]["current_step"]["linked_task_ids"] == []  # only verified ids
    assert payload["omitted_for_budget"]["roadmap_linked_tasks"] == 1


async def test_a_roadmap_with_no_steps_or_sparse_steps_is_valid(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    empty, sparse = await _project(db_session), await _project(db_session)
    await _import(db_session, principal, empty, _doc())
    section = (await _prepare(auth_ctx, empty, "plan"))["roadmap"]
    assert section["current_step"] is None and section["upcoming_steps"] == []
    assert section["progress"]["total"] == 0

    await _import(db_session, principal, sparse, _doc(("P", [_step("only")])))
    step = (await _prepare(auth_ctx, sparse, "plan"))["roadmap"]["current_step"]
    assert step["objective"] is None and step["acceptance_criteria"] == []
    assert step["linked_tasks"] == [] and step["linked_task_ids"] == []


# --- size, budget, truncation ------------------------------------------------------


async def test_a_large_roadmap_stays_bounded(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    phases = [
        (f"ph{p}", [_step(f"s{p}x{i}", objective="o" * 300) for i in range(30)]) for p in range(10)
    ]
    await _import(db_session, principal, project, _doc(*phases, objective="r" * 1500))
    payload = await _prepare(auth_ctx, project, "plan")
    section = payload["roadmap"]
    assert section["progress"]["total"] == 300
    assert len(section["upcoming_steps"]) == 5
    assert payload["additional_available"]["roadmap_upcoming_steps"] == 300 - 1 - 5
    assert len(json.dumps(section)) < 5_000
    assert payload["limits"]["chars_used"] <= payload["limits"]["max_chars"]


async def test_the_roadmap_slice_is_capped_and_never_starves_other_sources(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    document = _doc(
        (
            "P",
            [
                _step(
                    "a",
                    objective="o" * 600,
                    acceptance_criteria=[f"criterion {i} " + "c" * 480 for i in range(10)],
                ),
                *[_step(f"n{i}", title="t" * 150) for i in range(6)],
            ],
        ),
        objective="r" * 600,
    )
    await _import(db_session, principal, project, document)
    for i in range(5):
        await _decision(db_session, principal, project, f"Plan decision {i}", "d" * 800)
    payload = await _prepare(auth_ctx, project, "plan decision", max_chars=1000, limit=5)
    roadmap_spent = sum(
        len(v)
        for v in [
            payload["roadmap"]["current_step"]["objective"] or "",
            *payload["roadmap"]["current_step"]["acceptance_criteria"],
            payload["roadmap"]["objective"] or "",
            *[s["title"] for s in payload["roadmap"]["upcoming_steps"]],
            *payload["roadmap"]["blocking"],
        ]
    )
    assert roadmap_spent <= 250  # 25 % of max_chars
    assert payload["limits"]["chars_used"] <= 1000
    # the anchor of the section always survives
    assert payload["roadmap"]["current_step"]["key"] == "a"
    assert payload["roadmap"]["current_step"]["title"] == "Step a"
    # what did not fit is accounted for, never silently dropped
    omitted = payload["omitted_for_budget"]
    assert omitted.get("roadmap_criteria", 0) + omitted.get("roadmap_objective", 0) > 0
    # ... and the other sources kept the rest of the budget
    assert payload["returned"]["decisions"] >= 1


async def test_truncation_is_flagged_and_priority_order_is_respected(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    document = _doc(
        ("P", [_step("a", objective="o" * 2000, acceptance_criteria=["crit"]), _step("z")]),
        objective="secondary context",
    )
    await _import(db_session, principal, project, document)
    section = (await _prepare(auth_ctx, project, "plan"))["roadmap"]
    step = section["current_step"]
    assert len(step["objective"]) == roadmap_section.OBJECTIVE_CAP and step["truncated"] is True
    assert step["acceptance_criteria"] == ["crit"]
    assert section["objective"] == "secondary context"

    # a tight budget spends on the current step first and drops the secondary text
    tight = await _prepare(auth_ctx, project, "plan", max_chars=1000)
    assert tight["roadmap"]["current_step"]["objective"] is not None
    assert (
        tight["omitted_for_budget"].get("roadmap_context", 0)
        + tight["omitted_for_budget"].get("roadmap_upcoming_steps", 0)
        >= 1
    )


# --- unavailable source ------------------------------------------------------------


async def test_an_unreadable_roadmap_source_is_reported_not_fatal(
    db_session: AsyncSession,
    machine: Machine,
    auth_ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _decision(db_session, principal, project, "Plan decision", "still visible")

    async def broken(session: AsyncSession, *_a: Any, **_k: Any) -> None:
        await session.execute(text("SELECT * FROM table_that_does_not_exist"))
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    monkeypatch.setattr(roadmap_section.roadmaps_service, "list_roadmaps", broken)
    payload = await _prepare(auth_ctx, project, "plan decision")
    assert payload["unavailable"] == ["roadmap"]
    assert "roadmap" not in payload and "roadmap_overview" not in payload
    # the session was not poisoned: sources read afterwards still answer
    assert [d["title"] for d in payload["decisions"]] == ["Plan decision"]


async def test_any_failure_of_the_section_is_reported_and_refunds_its_budget(
    db_session: AsyncSession,
    machine: Machine,
    auth_ctx: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    roadmap = await _import(db_session, principal, project, CHAIN)
    task = await _task(db_session, principal, project, "Linked work")
    await roadmaps.link_task_by_step_key(db_session, principal, roadmap.id, "a", task.id)
    await _decision(db_session, principal, project, "Plan decision", "still visible")
    baseline = await _prepare(auth_ctx, project, "plan decision")

    async def explode(_session: AsyncSession, _task_id: uuid.UUID) -> None:
        raise ValueError("corrupt row")  # raised after the objective was already charged

    monkeypatch.setattr(roadmap_section.tasks_service, "get_task", explode)
    payload = await _prepare(auth_ctx, project, "plan decision")
    assert payload["unavailable"] == ["roadmap"] and "roadmap" not in payload
    assert not any(key.startswith("roadmap") for key in payload["omitted_for_budget"])
    # what the failed section had charged is refunded, not lost to the other sources
    assert payload["limits"]["chars_used"] == baseline["limits"]["chars_used"] - len(
        baseline["roadmap"]["current_step"]["objective"] or ""
    ) - len(baseline["roadmap"]["objective"] or "") - sum(
        len(c) for c in baseline["roadmap"]["current_step"]["acceptance_criteria"]
    ) - sum(len(s["title"]) for s in baseline["roadmap"]["upcoming_steps"]) - len(
        "Linked work"
    ) - sum(len(k) for k in baseline["roadmap"]["blocking"])
    assert [d["title"] for d in payload["decisions"]] == ["Plan decision"]


# --- interaction with the other sources -------------------------------------------


async def test_other_sources_are_unchanged_by_an_active_roadmap(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session, "Studio tooling")
    task = await _task(db_session, principal, project, "Git Watcher support", "watcher body")
    await _decision(db_session, principal, project, "Git Watcher choice", "body")
    await _library(db_session, principal, LibraryKind.RULE, "watcher-rule", "text")
    before = await _prepare(auth_ctx, project, "Git Watcher", task_id=str(task.id))
    await _import(db_session, principal, project, CHAIN)
    after = await _prepare(auth_ctx, project, "Git Watcher", task_id=str(task.id))
    for source in ("project", "task", "related_tasks", "decisions", "rules", "skills"):
        assert after[source] == before[source]
    assert after["active_work"] == before["active_work"]
    assert after["roadmap"]["current_step"]["key"] == "a"


async def test_read_only_callers_get_the_same_section(
    db_session: AsyncSession,
    machine: Machine,
    auth_ctx: FakeContext,
    readonly_auth_ctx: FakeContext,
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _import(db_session, principal, project, CHAIN)
    assert (await _prepare(readonly_auth_ctx, project, "plan"))["roadmap"] == (
        await _prepare(auth_ctx, project, "plan")
    )["roadmap"]


# --- determinism and neutrality ----------------------------------------------------


async def test_the_section_is_deterministic(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    roadmap = await _import(db_session, principal, project, CHAIN)
    tasks = [await _task(db_session, principal, project, f"Task {i}") for i in range(4)]
    for task in tasks:
        await roadmaps.link_task_by_step_key(db_session, principal, roadmap.id, "a", task.id)
    await _import(
        db_session,
        principal,
        project,
        _doc(("P", [_step("q")]), title="Later"),
        to=RoadmapStatus.DRAFT,
    )
    runs = [
        json.dumps(await _prepare(auth_ctx, project, "task plan"), sort_keys=True) for _ in range(3)
    ]
    assert len(set(runs)) == 1


async def test_the_section_is_neutral_no_provider_model_or_harness(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _import(db_session, principal, project, CHAIN)
    await _import(
        db_session,
        principal,
        project,
        _doc(("P", [_step("q")]), title="Later"),
        to=RoadmapStatus.DRAFT,
    )
    payload = await _prepare(auth_ctx, project, "plan")
    strings = " ".join(_all_strings(payload["roadmap"]) + _all_strings(payload["roadmap_overview"]))
    forbidden = (
        "claude", "anthropic", "openai", "opencode", "qwen", "codex", "gpt", "gemini",
        "provider", "model", "harness", "runtime",
    )  # fmt: skip
    assert not [word for word in forbidden if word in strings.lower()]


async def test_the_section_extends_the_shared_roadmap_context_contract(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _import(db_session, principal, project, CHAIN)
    principal_ctx = await roadmap_section.select_roadmap(
        db_session, principal, project.id, None, {}, 5, _Unlimited()
    )
    item = principal_ctx.item
    assert isinstance(item, RoadmapContext)
    assert all(
        isinstance(step, ContextStep) for step in [item.current_step, *item.upcoming_steps] if step
    )
    assert set(RoadmapContext.model_fields) <= set(type(item).model_fields)


class _Unlimited:
    def take(self, text: str, cap: int) -> tuple[str, bool] | None:
        return text[:cap], len(text) > cap

    def take_whole(self, text: str) -> bool:
        return True

    def mark(self) -> int:
        return 0

    def rollback(self, mark: int) -> None:
        return None


# --- the Roadmaps chantier itself --------------------------------------------------


def _chantier() -> dict[str, Any]:
    """The real Roadmaps plan: P1 contracts -> P2 domain / P3 API -> P4 MCP, P5
    initialization, P7 dashboard, P9 import/export -> P6 context, P8 review ->
    P10 reconciliation."""
    return _doc(
        (
            "roadmaps",
            [
                _step("p1", title="Contracts", objective="Common contracts"),
                _step("p2", title="Domain", depends_on=["p1"]),
                _step("p3", title="HTTP API", depends_on=["p1", "p2"]),
                _step("p4", title="MCP surface", depends_on=["p3"]),
                _step("p5", title="Initialization", depends_on=["p4"]),
                _step(
                    "p6",
                    title="Context integration",
                    objective="Roadmap in studio_prepare_context",
                    depends_on=["p4"],
                    acceptance_criteria=[
                        "Roadmap is optional: no roadmap never fails the context",
                        "Bounded by the shared budget, omissions reported",
                        "Deterministic and neutral",
                    ],
                ),
                _step("p7", title="Dashboard", depends_on=["p3"]),
                _step("p8", title="Review queue", depends_on=["p3", "p4"]),
                _step("p9", title="Import/export", depends_on=["p3"]),
                _step("p10", title="Reconciliation", depends_on=["p6", "p8"]),
            ],
        ),
        title="Roadmaps",
        objective="Structured, agent-agnostic project roadmaps",
    )


async def test_the_roadmaps_chantier_tells_an_agent_what_to_do_now(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    roadmap = await _import(db_session, principal, project, _chantier())
    await _done(db_session, principal, roadmap.id, "p1", "p2", "p3", "p4", "p5", "p7", "p9")
    p6 = await _task(db_session, principal, project, "[Roadmaps P6] Context integration")
    await roadmaps.link_task_by_step_key(db_session, principal, roadmap.id, "p6", p6.id)
    p6.status = "in_progress"
    await db_session.commit()

    payload = await _prepare(
        auth_ctx, project, "Roadmaps P6 context integration", task_id=str(p6.id)
    )
    section = payload["roadmap"]
    assert (section["title"], section["status"]) == ("Roadmaps", "active")
    assert section["progress"] == {"done": 7, "total": 10, "skipped": 0, "ratio": 0.7}
    assert section["current_phase_key"] == "roadmaps"
    step = section["current_step"]
    assert (step["key"], step["title"], step["state"]) == (
        "p6",
        "Context integration",
        "in_progress",
    )
    assert step["linked_tasks"] == [
        {"id": str(p6.id), "title": None, "status": None, "in_context": "task"}
    ]
    assert len(step["acceptance_criteria"]) == 3
    assert [s["key"] for s in section["upcoming_steps"]] == ["p8"]
    # p10 waits on p6 and p8, both workable now: nothing is stuck, so nothing blocks
    assert section["blocking"] == []
    assert section["task_step"] is None  # the requested Task is on the current step
    # the whole plan is not there: finished steps and p10's details stay out
    rendered = json.dumps(section)
    assert "Reconciliation" not in rendered and '"key": "p1"' not in rendered
