from __future__ import annotations

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.handoff import studio_handoff
from studio_mcp.tools.sessions import studio_get_sessions
from studio_mcp.tools.start_work import studio_start_work
from studio_mcp.tools.tasks import studio_create_task

from tests.mcp.conftest import FakeContext


async def test_get_sessions_filters_by_task(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Filtered task", auth_ctx)
    started = await studio_start_work(str(project.id), str(agent.id), auth_ctx, task_id=task["id"])
    result = await studio_get_sessions(auth_ctx, task_id=task["id"])
    assert any(s["id"] == started["session"]["id"] for s in result["sessions"])


async def test_get_sessions_filters_by_agent_and_open_state(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Open filter task", auth_ctx)
    started = await studio_start_work(str(project.id), str(agent.id), auth_ctx, task_id=task["id"])
    session_id = started["session"]["id"]
    ended = await studio_handoff(str(project.id), session_id, auth_ctx)
    assert "error_code" not in ended, ended

    still_open = await studio_get_sessions(auth_ctx, task_id=task["id"], open_only=True)
    assert still_open["sessions"] == []

    by_agent = await studio_get_sessions(auth_ctx, task_id=task["id"], agent_id=str(agent.id))
    assert [s["id"] for s in by_agent["sessions"]] == [session_id]
