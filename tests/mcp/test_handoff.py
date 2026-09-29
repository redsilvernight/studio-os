"""`studio_handoff` (L3/DEC-0163) over MCP: same composite as
`POST /handoff` — task status, claim release, AI work linked to the session,
session end; authorization before the idempotency short-circuit; typed
statuses with in-band errors. Real Postgres through the shared savepoint
fixtures."""

from __future__ import annotations

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.ai_work import studio_log_ai_work
from studio_mcp.tools.handoff import studio_handoff
from studio_mcp.tools.sessions import studio_start_session
from studio_mcp.tools.tasks import studio_claim_task, studio_create_task, studio_get_task

from tests.mcp.conftest import FakeContext


async def _task_with_session(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> tuple[dict[str, object], dict[str, object]]:
    task = await studio_create_task(str(project.id), "Close me", auth_ctx)
    claimed = await studio_claim_task(task["id"], auth_ctx, agent_id=str(agent.id))
    assert "error_code" not in claimed
    started = await studio_start_session(task["id"], auth_ctx, agent_id=str(agent.id))
    assert "error_code" not in started
    return task, started


async def test_handoff_closes_replays_and_links_ai_work(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task, started = await _task_with_session(auth_ctx, project, agent)
    current = await studio_get_task(task["id"], auth_ctx)
    body: dict[str, object] = {
        "expected_version": current["version"],
        "task_status": "completed",
        "agent_id": str(agent.id),
        "summary": "MCP close",
    }
    first = await studio_handoff(
        str(project.id), started["id"], auth_ctx, idempotency_key="mcp-handoff-1", **body
    )
    assert first["task_status"] == "completed"
    assert first["ai_work_id"] is not None

    # expected_version is consumed: replay the stored result, not the call.
    replayed = await studio_handoff(
        str(project.id), started["id"], auth_ctx, idempotency_key="mcp-handoff-1", **body
    )
    assert replayed == first


async def test_handoff_authorizes_before_idempotency_replay(
    auth_ctx: FakeContext, readonly_auth_ctx: FakeContext, project: ProjectModel
) -> None:
    task = await studio_create_task(str(project.id), "Guarded", auth_ctx)
    started = await studio_start_session(task["id"], auth_ctx)
    first = await studio_handoff(
        str(project.id), started["id"], auth_ctx, idempotency_key="mcp-handoff-guard"
    )
    assert "error_code" not in first

    replay = await studio_handoff(
        str(project.id), started["id"], readonly_auth_ctx, idempotency_key="mcp-handoff-guard"
    )
    assert replay["error_code"] == "forbidden"


async def test_handoff_rejects_unknown_statuses_in_band(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    task = await studio_create_task(str(project.id), "Statuses", auth_ctx)
    started = await studio_start_session(task["id"], auth_ctx)

    bad_task = await studio_handoff(str(project.id), started["id"], auth_ctx, task_status="shipped")
    assert bad_task["error_code"] == "invalid_task_status"

    bad_work = await studio_handoff(
        str(project.id), started["id"], auth_ctx, ai_work_status="shipped"
    )
    assert bad_work["error_code"] == "invalid_ai_work_status"


async def test_log_ai_work_rejects_foreign_session(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Mine", auth_ctx)
    other = await studio_create_task(str(project.id), "Theirs", auth_ctx)
    foreign = await studio_start_session(other["id"], auth_ctx)

    result = await studio_log_ai_work(
        str(project.id),
        "Foreign link",
        str(agent.id),
        auth_ctx,
        task_id=task["id"],
        session_id=foreign["id"],
    )
    assert result["error_code"] == "invalid_session"
