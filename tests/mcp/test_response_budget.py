"""Whole-response budget of the frequent MCP tools: `studio_handoff` answers a
minimal acknowledgement by default, `studio_start_work` stays within the
requested `max_chars` once serialized exactly as the MCP SDK emits it."""

from __future__ import annotations

import uuid

import pytest
from mcp.server.mcpserver.utilities.func_metadata import _convert_to_content
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.response_budget import (
    HANDOFF_ACK_MAX_CHARS,
    fit_roadmap,
    fit_start_work,
    fit_sync,
    handoff_ack,
    rendered_chars,
)
from studio_mcp.tools.claims import studio_claim_resources
from studio_mcp.tools.decisions import studio_add_decision
from studio_mcp.tools.handoff import studio_handoff
from studio_mcp.tools.start_work import studio_start_work
from studio_mcp.tools.tasks import studio_create_task, studio_get_task

from tests.mcp.conftest import FakeContext

LONG = "budget contexte reponse " * 200


def _text(payload: object) -> str:
    content = _convert_to_content(payload)
    return content[0].text  # type: ignore[union-attr]


def test_rendered_chars_matches_the_sdk_text_content() -> None:
    payload = {"id": str(uuid.uuid4()), "items": [{"a": 1, "b": None}], "text": "é"}
    assert rendered_chars(payload) == len(_text(payload))


async def _heavy_project(auth_ctx: FakeContext, project: ProjectModel) -> dict[str, object]:
    task = await studio_create_task(
        str(project.id), "Budget contexte principal", auth_ctx, description=LONG
    )
    for index in range(8):
        await studio_create_task(
            str(project.id), f"Budget contexte voisin {index}", auth_ctx, description=LONG
        )
        await studio_add_decision(
            f"Budget contexte decision {index}",
            LONG,
            auth_ctx,
            project_id=str(project.id),
            task_id=task["id"],
        )
    return task


@pytest.mark.parametrize("max_chars", [1_000, 3_000, 12_000])
async def test_start_work_answer_fits_max_chars(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel, max_chars: int
) -> None:
    task = await _heavy_project(auth_ctx, project)

    for verbose in (False, True):
        result = await studio_start_work(
            str(project.id),
            str(agent.id),
            auth_ctx,
            task_id=task["id"],
            limit=20,
            max_chars=max_chars,
            verbose=verbose,
        )
        assert "error_code" not in result
        assert len(_text(result)) <= max_chars
        assert result["task"]["id"] == task["id"]
        assert result["session"]["id"]

    no_task = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, limit=20, max_chars=max_chars
    )
    assert len(_text(no_task)) <= max_chars


async def test_start_work_counts_what_it_trims(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await _heavy_project(auth_ctx, project)
    result = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"], limit=20, max_chars=3_000
    )
    assert result["trimmed_for_budget"]
    assert result["prepared_context"] is not None
    assert result["task"]["version"] >= 1
    assert "description" not in result["task"]


async def test_start_work_compact_and_verbose_keys_differ_in_idempotency(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Shape", auth_ctx)
    await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"], idempotency_key="sw-shape"
    )
    mismatch = await studio_start_work(
        str(project.id),
        str(agent.id),
        auth_ctx,
        task_id=task["id"],
        idempotency_key="sw-shape",
        verbose=True,
    )
    assert mismatch["error_code"] == "idempotency_key_payload_mismatch"


async def test_handoff_default_is_a_minimal_ack(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    started = await studio_start_work(
        str(project.id),
        str(agent.id),
        auth_ctx,
        task_id=(await studio_create_task(str(project.id), "Close", auth_ctx))["id"],
    )
    task_id = started["task"]["id"]
    session_id = started["session"]["id"]
    claimed = await studio_claim_resources(
        str(project.id),
        [f"src/module_{index}/file.py" for index in range(10)],
        "file",
        600,
        auth_ctx,
        task_id=task_id,
        agent_id=str(agent.id),
    )
    assert "error_code" not in claimed
    current = await studio_get_task(task_id, auth_ctx)

    ack = await studio_handoff(
        str(project.id),
        session_id,
        auth_ctx,
        expected_version=current["version"],
        task_status="completed",
        agent_id=str(agent.id),
        summary="x" * 2000,
        changed_files=[f"src/module_{index}/file.py" for index in range(100)],
        tests_run=[f"tests/test_{index}.py" for index in range(100)],
        coordination_text="y" * 280,
        idempotency_key="handoff-ack",
    )
    assert "error_code" not in ack
    assert len(_text(ack)) <= HANDOFF_ACK_MAX_CHARS
    assert ack["task_status"] == "completed"
    assert ack["released_claims"] == 10
    assert ack["ai_work_id"] is not None
    assert ack["coordination_event_id"] is not None
    assert "sync" not in ack


async def test_handoff_verbose_keeps_the_full_answer(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    started = await studio_start_work(
        str(project.id),
        str(agent.id),
        auth_ctx,
        task_id=(await studio_create_task(str(project.id), "Verbose", auth_ctx))["id"],
    )
    full = await studio_handoff(str(project.id), started["session"]["id"], auth_ctx, verbose=True)
    assert isinstance(full["released_claims"], list)
    assert "next_cursor" in full["sync"]


def _sync_item(seq: int | None, why: str = "task_event") -> dict[str, object]:
    return {
        "kind": "event" if seq is not None else "claim",
        "why": why,
        "seq": seq,
        "event_type": "task.updated" if seq is not None else None,
        "task_id": str(uuid.uuid4()),
        "claim_id": None,
        "resource_path": None,
        "coordination": None,
    }


def test_fit_sync_keeps_the_cursor_below_evicted_events() -> None:
    block = {
        "next_cursor": 140,
        "items": [_sync_item(100 + index) for index in range(41)],
        "overflow": {},
        "resync": False,
    }
    fitted = fit_sync(block, 1_000)
    assert rendered_chars(fitted) <= 1_000
    kept = [item["seq"] for item in fitted["items"]]
    assert kept == list(range(100, 100 + len(kept)))
    assert fitted["next_cursor"] == 100 + len(kept) - 1
    assert sum(fitted["overflow"].values()) == 41 - len(kept)


def test_fit_start_work_falls_back_to_a_minimal_answer() -> None:
    payload = {
        "claimed": True,
        "resumed": False,
        "task": {"id": str(uuid.uuid4()), "status": "claimed", "version": 2, "title": "t" * 5000},
        "session": {"id": str(uuid.uuid4())},
        "prepared_context": {"project": {"id": "p", "slug": "s" * 5000}},
        "candidates": [],
        "sync": None,
    }
    fitted = fit_start_work(payload, 1_000)
    assert rendered_chars(fitted) <= 1_000
    assert fitted["task"]["version"] == 2
    assert fitted["trimmed_for_budget"]["prepared_context"] == 1


def test_fit_roadmap_bounds_per_field_texts() -> None:
    step = {
        "key": "s1",
        "title": "Step",
        "state": "available",
        "available": True,
        "waiting_on": [],
        "acceptance_criteria": ["c" * 2000 for _ in range(10)],
        "objective": "o" * 5000,
        "linked_task_ids": [str(uuid.uuid4()) for _ in range(20)],
        "truncated": False,
    }
    payload = {
        "project_id": str(uuid.uuid4()),
        "roadmaps": [{"id": str(uuid.uuid4()), "title": "r" * 500} for _ in range(20)],
        "active": {
            "roadmap_id": str(uuid.uuid4()),
            "status": "active",
            "current_step_key": "s1",
            "current_step": step,
            "upcoming_steps": [dict(step, key=f"s{i}") for i in range(2, 7)],
        },
        "draft_pending": 0,
        "pending_proposals": [{"id": str(uuid.uuid4()), "summary": "p" * 3000}] * 5,
        "omitted_for_budget": 0,
    }
    fitted = fit_roadmap(payload, 3_000)
    assert rendered_chars(fitted) <= 3_000
    assert fitted["trimmed_for_budget"]


def test_handoff_ack_reports_sync_warnings() -> None:
    ack = handoff_ack(
        {
            "task_id": str(uuid.uuid4()),
            "task_status": "completed",
            "task_version": 3,
            "session_id": str(uuid.uuid4()),
            "released_claims": [str(uuid.uuid4()) for _ in range(100)],
            "ai_work_id": None,
            "sync": {
                "next_cursor": 9,
                "items": [
                    {**_sync_item(5, "coordination"), "coordination": {"intent": "handoff"}},
                    _sync_item(6),
                ],
                "overflow": {"task_event": 4},
                "resync": True,
            },
            "handoff_cursor_seq": 9,
            "coordination_event_id": None,
        }
    )
    assert rendered_chars(ack) <= HANDOFF_ACK_MAX_CHARS
    assert ack["released_claims"] == 100
    assert ack["warnings"] == [
        "coordination_signals_received:1",
        "sync_items_acknowledged:1",
        "sync_overflow:4",
        "sync_resync",
    ]
