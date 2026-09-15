from __future__ import annotations

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.ai_work import studio_log_ai_work
from studio_mcp.tools.review_queue import studio_get_review_queue

from tests.mcp.conftest import FakeContext


async def test_get_review_queue_empty(auth_ctx: FakeContext, project: ProjectModel) -> None:
    result = await studio_get_review_queue(auth_ctx, project_id=str(project.id))
    assert result["items"] == []


async def test_get_review_queue_includes_ai_work_review(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    created = await studio_log_ai_work(str(project.id), "Needs review", str(agent.id), auth_ctx)
    await studio_log_ai_work(
        str(project.id),
        "Needs review",
        str(agent.id),
        auth_ctx,
        ai_work_id=created["id"],
        status="review_requested",
    )

    result = await studio_get_review_queue(auth_ctx, project_id=str(project.id))
    assert len(result["items"]) == 1
    assert result["items"][0]["kind"] == "ai_work_review"
    assert result["items"][0]["id"] == created["id"]


async def test_get_review_queue_filters_by_project(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    created = await studio_log_ai_work(str(project.id), "In scope", str(agent.id), auth_ctx)
    await studio_log_ai_work(
        str(project.id),
        "In scope",
        str(agent.id),
        auth_ctx,
        ai_work_id=created["id"],
        status="review_requested",
    )

    other_project_id = "00000000-0000-0000-0000-000000000000"
    result = await studio_get_review_queue(auth_ctx, project_id=other_project_id)
    assert result["items"] == []


async def test_get_review_queue_rejects_invalid_project_id(auth_ctx: FakeContext) -> None:
    result = await studio_get_review_queue(auth_ctx, project_id="not-a-uuid")
    assert result["error_code"] == "invalid_argument"
