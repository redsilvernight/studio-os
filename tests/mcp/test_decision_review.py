"""DEC-0363 over MCP: v1 handoff warnings reach the ack, and closing a
roadmap step re-surfaces linked tasks without a decision review — read-only,
never a gate. Real Postgres through the shared savepoint fixtures."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import roadmap_structure as structure_service
from studio_api.services.authz import Principal
from studio_contracts.completion import CompletionEvidence
from studio_contracts.roadmaps import LinkTask, RoadmapDocument
from studio_mcp.errors import run_tool
from studio_mcp.tools.handoff import studio_handoff
from studio_mcp.tools.roadmaps import studio_propose_roadmap, studio_update_roadmap_step
from studio_mcp.tools.start_work import studio_start_work
from studio_mcp.tools.tasks import studio_create_task, studio_get_task

from tests.mcp.conftest import FakeContext

_PLAN: dict[str, Any] = {
    "format": "studio.roadmap/v1",
    "title": "Decisions roadmap",
    "objective": "Cover step closure warnings",
    "phases": [
        {
            "key": "P1",
            "title": "Phase one",
            "steps": [{"key": "S1", "title": "First step", "acceptance_criteria": ["done"]}],
        }
    ],
}


def _evidence(**extra: Any) -> CompletionEvidence:
    return CompletionEvidence.model_validate(
        {
            "kind": "audit",
            "artifacts": ["vault:report"],
            "checks": [{"name": "report review", "kind": "review", "status": "passed"}],
            **extra,
        }
    )


async def _task_with_session(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> tuple[dict[str, Any], dict[str, Any]]:
    task = await studio_create_task(str(project.id), "Close me", auth_ctx)
    started = await studio_start_work(str(project.id), str(agent.id), auth_ctx, task_id=task["id"])
    assert "error_code" not in started
    return task, started["session"]


async def _close(
    auth_ctx: FakeContext,
    project: ProjectModel,
    agent: AgentModel,
    evidence: CompletionEvidence,
    key: str,
) -> dict[str, Any]:
    task, started = await _task_with_session(auth_ctx, project, agent)
    current = await studio_get_task(task["id"], auth_ctx)
    return await studio_handoff(
        str(project.id),
        started["id"],
        auth_ctx,
        expected_version=current["version"],
        task_status="completed",
        agent_id=str(agent.id),
        summary="Verified audit",
        completion=evidence,
        idempotency_key=key,
        verbose=True,
    )


async def test_v1_handoff_without_review_warns_in_ack_and_verbose(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    result = await _close(auth_ctx, project, agent, _evidence(), "dec-review-ack-1")
    assert "error_code" not in result
    assert result["task_status"] == "completed"
    assert result["warnings"] == ["decision_review_missing"]


async def test_v1_handoff_with_review_has_no_decision_warning(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    result = await _close(
        auth_ctx,
        project,
        agent,
        _evidence(decisions={"outcome": "none", "reason": "No decision involved."}),
        "dec-review-ack-2",
    )
    assert "error_code" not in result
    assert "decision_review_missing" not in result.get("warnings", [])


async def test_v1_handoff_warning_replay_is_stable(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task, started = await _task_with_session(auth_ctx, project, agent)
    current = await studio_get_task(task["id"], auth_ctx)
    body: dict[str, Any] = {
        "expected_version": current["version"],
        "task_status": "completed",
        "agent_id": str(agent.id),
        "summary": "Verified audit",
        "completion": _evidence(),
    }
    first = await studio_handoff(
        str(project.id), started["id"], auth_ctx, idempotency_key="dec-review-replay", **body
    )
    assert first["warnings"] == ["decision_review_missing"]
    assert (
        await studio_handoff(
            str(project.id), started["id"], auth_ctx, idempotency_key="dec-review-replay", **body
        )
        == first
    )


async def _step_version(auth_ctx: FakeContext, roadmap_id: str, key: str) -> int:
    async def _handler(session: AsyncSession, principal: Principal) -> int:
        from studio_mcp.tools.roadmaps import _roadmaps

        roadmap = await _roadmaps().get_roadmap(session, principal, UUID(roadmap_id))
        for phase in roadmap.phases:
            for step in phase.steps:
                if step.key == key:
                    return step.version
        raise AssertionError(f"no step {key}")

    return await run_tool(auth_ctx, _handler)


async def _propose_and_link(auth_ctx: FakeContext, project: ProjectModel, task_id: str) -> str:
    proposed = await studio_propose_roadmap(
        str(project.id), RoadmapDocument.model_validate(_PLAN), auth_ctx, submit=False
    )
    assert "error_code" not in proposed, proposed
    roadmap_id = proposed["id"]

    async def _link(session: AsyncSession, principal: Principal) -> None:
        await structure_service.link_task(
            session, principal, UUID(roadmap_id), "S1", LinkTask(task_id=UUID(task_id))
        )

    await run_tool(auth_ctx, _link)
    return roadmap_id


async def test_closing_step_surfaces_linked_task_without_review(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Linked work", auth_ctx)
    roadmap_id = await _propose_and_link(auth_ctx, project, task["id"])

    closed = await studio_update_roadmap_step(
        roadmap_id,
        "S1",
        await _step_version(auth_ctx, roadmap_id, "S1"),
        auth_ctx,
        state_override="done",
    )
    assert "error_code" not in closed, closed
    assert closed["decision_review_warnings"] == [f"decision_review_missing:{task['id']}"]


async def test_step_update_without_done_closure_has_no_review_warning(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Linked work", auth_ctx)
    roadmap_id = await _propose_and_link(auth_ctx, project, task["id"])

    noted = await studio_update_roadmap_step(
        roadmap_id,
        "S1",
        await _step_version(auth_ctx, roadmap_id, "S1"),
        auth_ctx,
        notes="still working",
    )
    assert "error_code" not in noted, noted
    assert "decision_review_warnings" not in noted
    assert noted["state"] != "done"


async def test_closing_step_after_reviewed_handoff_is_quiet(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Linked work", auth_ctx)
    roadmap_id = await _propose_and_link(auth_ctx, project, task["id"])
    started = await studio_start_work(str(project.id), str(agent.id), auth_ctx, task_id=task["id"])
    assert "error_code" not in started
    current = await studio_get_task(task["id"], auth_ctx)
    closed_task = await studio_handoff(
        str(project.id),
        started["session"]["id"],
        auth_ctx,
        expected_version=current["version"],
        task_status="completed",
        agent_id=str(agent.id),
        summary="Verified audit",
        completion=_evidence(decisions={"outcome": "none", "reason": "No decision involved."}),
        idempotency_key=f"dec-review-link-{uuid.uuid4().hex[:8]}",
    )
    assert "error_code" not in closed_task, closed_task

    closed = await studio_update_roadmap_step(
        roadmap_id,
        "S1",
        await _step_version(auth_ctx, roadmap_id, "S1"),
        auth_ctx,
        state_override="done",
    )
    assert "error_code" not in closed, closed
    assert closed["decision_review_warnings"] == []
