"""Role × account state × project access over MCP and the SSE revalidation
(A3, task 0e337d4b): an inactive account has no principal (`unauthenticated`,
stream closed); an active one is filtered by project access (DEC-0103)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.project import ProjectModel
from studio_api.services import events as events_service
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_mcp.tools.context import studio_prepare_context
from studio_mcp.tools.projects import studio_get_projects
from studio_mcp.tools.review_queue import studio_get_review_queue

from tests.mcp.conftest import FakeContext

pytestmark = pytest.mark.isolation

ROLES = ("admin", "developer", "readonly", "agent")
STATES = ("active", "pending", "disabled")


def _dump(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    assert isinstance(result, dict)
    return result


@pytest.mark.parametrize("member", [True, False])
@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("role", ROLES)
async def test_mcp_and_stream_matrix(
    db_session: AsyncSession, project: ProjectModel, role: str, state: str, member: bool
) -> None:
    user = await provisioning_service.create_user(
        db_session, "Matrix User", f"{uuid.uuid4()}@example.test", role
    )
    machine, token = await provisioning_service.create_machine(db_session, user.id, "matrix")
    if member:
        await projects_service.grant_member(
            db_session, project.id, user.id, granted_by_user_id=None
        )
    if state == "pending":
        user.email_verified_at = None
        await db_session.flush()
    elif state == "disabled":
        await provisioning_service.disable_user(db_session, user.email)
    ctx = FakeContext(headers={"authorization": f"Bearer {token}"})
    pid = str(project.id)

    results = {
        "projects": _dump(await studio_get_projects(ctx=ctx)),
        "context": _dump(await studio_prepare_context(project_id=pid, objective="matrix", ctx=ctx)),
        "review": _dump(await studio_get_review_queue(ctx=ctx, project_id=pid)),
    }
    stream_open = await events_service.stream_access_still_valid(machine.id, project.id)

    if state != "active":
        assert {r.get("error_code") for r in results.values()} == {"unauthenticated"}
        assert stream_open is False
        return

    sees_project = member or role == "admin"
    assert "error_code" not in results["projects"]
    assert (pid in {p["id"] for p in results["projects"]["projects"]}) is sees_project
    for name in ("context", "review"):
        if sees_project:
            assert "error_code" not in results[name], (name, results[name])
        else:
            assert results[name]["error_code"] == "forbidden", (name, results[name])
            assert results[name]["resource"] == "project"
    assert stream_open is sees_project
