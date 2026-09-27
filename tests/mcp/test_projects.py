from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import projects as projects_service
from studio_api.services.authz import load_principal
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


@pytest.mark.isolation
async def test_get_project_state_unknown_project_is_forbidden_for_non_admin(
    auth_ctx: FakeContext,
) -> None:
    """No existence oracle (DEC-0103 §3): nonexistent looks like inaccessible."""
    result = await studio_get_project_state("00000000-0000-0000-0000-000000000000", auth_ctx)
    assert result == {"error_code": "forbidden", "resource": "project", "action": "read"}


async def test_get_project_state_unknown_project_is_not_found_for_admin(
    admin_ctx: FakeContext,
) -> None:
    result = await studio_get_project_state("00000000-0000-0000-0000-000000000000", admin_ctx)
    assert result["error_code"] == "not_found"


@pytest.mark.isolation
async def test_non_member_neither_lists_nor_reads_a_project(
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    """Same service as HTTP (`run_tool` -> `load_principal`): the MCP surface
    enforces membership exactly like the API."""
    principal = await load_principal(db_session, machine[0])
    project = await projects_service.create_project(
        db_session, f"iso-{uuid.uuid4().hex[:8]}", "Iso", None, creator=principal.user
    )

    mine = await studio_get_projects(auth_ctx)
    theirs = await studio_get_projects(other_auth_ctx)
    assert [p["id"] for p in mine["projects"]] == [str(project.id)]
    assert theirs["projects"] == []

    assert (await studio_get_project_state(str(project.id), auth_ctx))["project_id"] == str(
        project.id
    )
    assert (await studio_get_project_state(str(project.id), other_auth_ctx)) == {
        "error_code": "forbidden",
        "resource": "project",
        "action": "read",
    }
