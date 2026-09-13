from __future__ import annotations

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.ai_work import studio_get_ai_work, studio_log_ai_work

from tests.mcp.conftest import FakeContext


async def test_log_ai_work_creates_started_entry(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    result = await studio_log_ai_work(str(project.id), "Implement étape 5", str(agent.id), auth_ctx)
    assert result["status"] == "started"
    assert result["ended_at"] is None


async def test_log_ai_work_updates_existing_entry_to_completed(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    created = await studio_log_ai_work(
        str(project.id), "Implement étape 5", str(agent.id), auth_ctx
    )
    updated = await studio_log_ai_work(
        str(project.id),
        "Implement étape 5",
        str(agent.id),
        auth_ctx,
        ai_work_id=created["id"],
        status="completed",
        changed_files=["services/mcp/src/studio_mcp/server.py"],
        tests_run=["tests/mcp/test_ai_work.py"],
    )
    assert updated["status"] == "completed"
    assert updated["ended_at"] is not None
    assert updated["changed_files"] == ["services/mcp/src/studio_mcp/server.py"]


async def test_log_ai_work_rejects_unknown_agent(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_log_ai_work(
        str(project.id), "Orphan work", "00000000-0000-0000-0000-000000000000", auth_ctx
    )
    assert result["error_code"] == "invalid_reference"


async def test_log_ai_work_rejects_unknown_existing_id(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    result = await studio_log_ai_work(
        str(project.id),
        "Update on missing entry",
        str(agent.id),
        auth_ctx,
        ai_work_id="00000000-0000-0000-0000-000000000000",
    )
    assert result["error_code"] == "not_found"


async def test_get_ai_work_filters_by_project(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    created = await studio_log_ai_work(str(project.id), "Filtered work", str(agent.id), auth_ctx)
    result = await studio_get_ai_work(auth_ctx, project_id=str(project.id))
    assert any(w["id"] == created["id"] for w in result["ai_work"])
