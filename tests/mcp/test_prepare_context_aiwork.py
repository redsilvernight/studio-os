"""P2.3/P2.5 — AI work continuity and session lifecycle events in context.

Needs Postgres (same as the rest of `tests/mcp/`); runs in CI.
Scenario: Agent A works (task, decision, AI work handoff, session), then a
logically fresh Agent B — no history passed — resumes from one
`studio_prepare_context` call.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import ai_work as ai_work_service
from studio_api.services import decisions as decisions_service
from studio_api.services import events as events_service
from studio_api.services import projects as projects_service
from studio_api.services import sessions as sessions_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.ai_work import AIWorkLogCreate, AIWorkLogUpdate
from studio_contracts.decisions import DecisionCreate
from studio_contracts.sessions import WorkSessionCreate
from studio_contracts.tasks import TaskCreate
from studio_mcp.tools.context import studio_prepare_context

from tests.mcp.conftest import FakeContext

Machine = tuple[MachineModel, str]

HANDOFF_SUMMARY = (
    "DONE migrate claim TTL index. STATE task in_progress, session closed. "
    "CHANGED services/api/src/studio_api/services/claims.py. TESTS pytest tests/mcp/. "
    "NEXT update the dashboard TTL label. BLOCKERS none."
)


def dump(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    assert isinstance(result, dict)
    return result


async def _principal(db_session: AsyncSession, machine: Machine) -> Principal:
    return await load_principal(db_session, machine[0])


async def _task(db_session, principal, project, title, description="work"):
    return await tasks_service.create_task(
        db_session,
        principal,
        TaskCreate(project_id=project.id, title=title, description=description),
    )


async def _log(
    db_session,
    principal,
    project,
    agent,
    task_id,
    summary,
    status="completed",
    files=None,
    tests=None,
):
    work = await ai_work_service.create_ai_work(
        db_session,
        principal,
        AIWorkLogCreate(
            project_id=project.id, agent_id=agent.id, task_id=task_id, summary=summary
        ),
    )
    return await ai_work_service.update_ai_work(
        db_session,
        principal,
        work,
        AIWorkLogUpdate(status=status, changed_files=files or [], tests_run=tests or []),
    )


async def _project(db_session) -> ProjectModel:
    return await projects_service.create_project(
        db_session, f"ctx-{uuid.uuid4().hex[:8]}", "Context Project", None
    )


async def _prepare(auth_ctx, project, objective, **kwargs):
    return dump(await studio_prepare_context(str(project.id), objective, auth_ctx, **kwargs))


async def test_linked_ai_work_included_unrelated_excluded(
    db_session: AsyncSession, machine: Machine, agent: AgentModel, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project, "Migrate claim TTL index")
    other = await _task(db_session, principal, project, "Repaint dashboard header")
    files = [f"services/api/src/studio_api/services/m{i}.py" for i in range(12)]
    await _log(
        db_session, principal, project, agent, task.id, HANDOFF_SUMMARY,
        files=files, tests=["pytest tests/mcp/"],
    )
    await _log(db_session, principal, project, agent, other.id, "Unrelated repaint notes")

    result = await _prepare(
        auth_ctx, project, "migrate claim TTL index", task_id=str(task.id)
    )

    assert result["task"]["id"] == str(task.id)
    assert result["returned"]["ai_work"] == 1
    assert result["additional_available"]["ai_work"] == 1
    (entry,) = result["ai_work"]
    assert entry["why"]["reason"] == "linked_to_task"
    assert "NEXT update the dashboard TTL label" in entry["summary"]
    assert entry["changed_files"] == files[:10]
    assert entry["truncated"] is True
    assert entry["tests_run"] == ["pytest tests/mcp/"]


async def test_irrelevant_ai_work_excluded_but_counted(
    db_session: AsyncSession, machine: Machine, agent: AgentModel, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project, "Migrate claim TTL index")
    await _log(db_session, principal, project, agent, task.id, HANDOFF_SUMMARY)

    result = await _prepare(auth_ctx, project, "completely different zephyr quokka")

    assert result["ai_work"] == []
    assert result["additional_available"]["ai_work"] == 1
    assert result["returned"]["ai_work"] == 0


async def test_ai_work_has_own_budget_slice(
    db_session: AsyncSession, machine: Machine, agent: AgentModel, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project, "Migrate claim TTL index")
    await _log(db_session, principal, project, agent, task.id, "x" * 5_000)

    result = await _prepare(
        auth_ctx, project, "migrate claim TTL", task_id=str(task.id), max_chars=1_000
    )

    assert result["limits"]["chars_used"] <= 1_000
    assert result["omitted_for_budget"].get("ai_work", 0) >= 1


async def test_agent_a_to_b_handoff_resumes_from_one_call(
    db_session: AsyncSession, machine: Machine, agent: AgentModel, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)

    # --- Agent A: work, decide, trace, close. No history leaves this block. ---
    task = await _task(db_session, principal, project, "Migrate claim TTL index")
    await decisions_service.create_decision(
        db_session,
        principal,
        DecisionCreate(
            project_id=project.id,
            task_id=task.id,
            title="TTL index over expires_at",
            body="A partial index keeps claim checks fast.",
            proposed_by_type="agent",
            proposed_by_id=principal.user.id,
        ),
    )
    work_session = await sessions_service.start_session(
        db_session,
        principal,
        WorkSessionCreate(task_id=task.id, machine_id=machine[0].id, agent_id=agent.id),
    )
    await _log(db_session, principal, project, agent, task.id, HANDOFF_SUMMARY)
    first_end = await sessions_service.end_session(db_session, principal, work_session.id)

    # --- Agent B: logically fresh, one bounded call. ---
    result = await _prepare(
        auth_ctx, project, "migrate claim TTL index", task_id=str(task.id)
    )

    assert result["task"]["id"] == str(task.id)
    assert result["task"]["status"] == "created"
    assert any("NEXT update the dashboard TTL label" in e["summary"] for e in result["ai_work"])
    assert any(d["title"] == "TTL index over expires_at" for d in result["decisions"])

    events = await events_service.list_events(db_session, project_id=str(project.id))
    kinds = {e.event_type for e in events}
    assert "session.started" in kinds and "session.ended" in kinds

    # Ending twice is the documented harmless no-op: same timestamp, no new event.
    second_end = await sessions_service.end_session(db_session, principal, work_session.id)
    assert second_end.ended_at == first_end.ended_at
    events_after = await events_service.list_events(db_session, project_id=str(project.id))
    assert sum(1 for e in events_after if e.event_type == "session.ended") == 1