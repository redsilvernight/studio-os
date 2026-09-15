from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.projects import studio_get_project_state, studio_get_projects

from tests.mcp.conftest import FakeContext


async def test_get_projects_lists_created_project(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_get_projects(auth_ctx)
    assert any(p["id"] == str(project.id) for p in result["projects"])


async def test_get_projects_rejects_unauthenticated_call(db_session: AsyncSession) -> None:
    result = await studio_get_projects(FakeContext(headers=None))
    assert result["error_code"] == "unauthenticated"


async def test_get_project_state_returns_active_tasks_and_claims(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_get_project_state(str(project.id), auth_ctx)
    assert result["project_id"] == str(project.id)
    assert result["active_tasks"] == []
    assert result["active_claims"] == []


async def test_get_project_state_rejects_bad_uuid(auth_ctx: FakeContext) -> None:
    result = await studio_get_project_state("not-a-uuid", auth_ctx)
    assert result["error_code"] == "invalid_argument"


async def test_get_project_state_rejects_unknown_project(auth_ctx: FakeContext) -> None:
    result = await studio_get_project_state("00000000-0000-0000-0000-000000000000", auth_ctx)
    assert result["error_code"] == "not_found"
