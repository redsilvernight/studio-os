from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.services import launch_credentials as credentials_service
from studio_api.services import projects as projects_service
from studio_api.services.authz import load_principal
from studio_mcp.tools.projects import studio_get_projects
from studio_mcp.tools.tasks import studio_create_task, studio_get_task

from tests.mcp.conftest import FakeContext


async def _ephemeral_ctx(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    task_id: str,
    *,
    status: str = "running",
) -> tuple[FakeContext, TaskLaunchModel]:
    model, _ = machine
    launch = TaskLaunchModel(
        id=uuid.uuid4(),
        project_id=project.id,
        task_id=uuid.UUID(task_id),
        machine_id=model.id,
        requested_by_user_id=model.owner_user_id,
        harness_id="claude-code",
        status=status,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(launch)
    await db_session.commit()
    principal = await load_principal(db_session, model)
    issued = await credentials_service.issue_credential(db_session, principal, launch)
    return FakeContext(headers={"authorization": f"Bearer {issued.token}"}), launch


async def test_allowlisted_tool_is_scoped_to_the_launch_project(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
    project: ProjectModel,
) -> None:
    other = await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Other", None, creator=None
    )
    own_task = await studio_create_task(str(project.id), "own", auth_ctx)
    foreign_task = await studio_create_task(str(other.id), "foreign", auth_ctx)
    ephemeral, _ = await _ephemeral_ctx(db_session, machine, project, own_task["id"])

    own = await studio_get_task(own_task["id"], ephemeral)
    foreign = await studio_get_task(foreign_task["id"], ephemeral)

    assert own["id"] == own_task["id"]
    assert foreign.get("error_code") == "forbidden"


@pytest.mark.parametrize("call", ["projects", "create_task"])
async def test_tools_outside_the_allowlist_are_refused(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
    project: ProjectModel,
    call: str,
) -> None:
    task = await studio_create_task(str(project.id), "t", auth_ctx)
    ephemeral, _ = await _ephemeral_ctx(db_session, machine, project, task["id"])

    if call == "projects":
        result = await studio_get_projects(ephemeral)
    else:
        result = await studio_create_task(str(project.id), "new", ephemeral)

    assert result["error_code"] == "launch_credential_scope"


async def test_credential_is_unauthenticated_once_the_launch_is_terminal(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
    project: ProjectModel,
) -> None:
    task = await studio_create_task(str(project.id), "t", auth_ctx)
    ephemeral, launch = await _ephemeral_ctx(db_session, machine, project, task["id"])
    assert (await studio_get_task(task["id"], ephemeral))["id"] == task["id"]

    launch.status = "failed"
    await db_session.commit()

    assert (await studio_get_task(task["id"], ephemeral))["error_code"] == "unauthenticated"


async def test_every_allowlisted_tool_is_a_registered_tool() -> None:
    from studio_mcp.access_registry import MCP_ACCESS

    assert credentials_service.LAUNCH_MCP_ALLOWLIST <= set(MCP_ACCESS)
