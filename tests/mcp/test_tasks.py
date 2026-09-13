from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import provisioning as provisioning_service
from studio_mcp.tools.tasks import (
    studio_claim_task,
    studio_create_task,
    studio_get_active_tasks,
    studio_get_task,
    studio_release_task,
    studio_update_task,
)

from tests.mcp.conftest import FakeContext


async def test_create_and_get_task(auth_ctx: FakeContext, project: ProjectModel) -> None:
    created = await studio_create_task(str(project.id), "Design the level", auth_ctx)
    assert created["status"] == "created"

    fetched = await studio_get_task(created["id"], auth_ctx)
    assert fetched["id"] == created["id"]
    assert fetched["title"] == "Design the level"


async def test_get_task_rejects_unknown_id(auth_ctx: FakeContext) -> None:
    result = await studio_get_task("00000000-0000-0000-0000-000000000000", auth_ctx)
    assert result["error_code"] == "not_found"


async def test_get_active_tasks_lists_created_task(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_task(str(project.id), "Fix the bug", auth_ctx)
    result = await studio_get_active_tasks(str(project.id), auth_ctx)
    assert any(t["id"] == created["id"] for t in result["tasks"])


async def test_claim_then_release_task(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    created = await studio_create_task(str(project.id), "Ship it", auth_ctx)

    claimed = await studio_claim_task(created["id"], auth_ctx)
    assert claimed["status"] == "in_progress"
    assert claimed["claimed_by_machine_id"] == str(machine_model.id)

    released = await studio_release_task(created["id"], auth_ctx)
    assert released["claimed_by_machine_id"] is None


async def test_claim_task_conflicts_when_already_claimed(
    auth_ctx: FakeContext, project: ProjectModel, db_session: AsyncSession
) -> None:
    created = await studio_create_task(str(project.id), "Contested task", auth_ctx)
    await studio_claim_task(created["id"], auth_ctx)

    other_user = await provisioning_service.create_user(
        db_session, "Other Dev", "other-dev@example.test", "developer"
    )
    _, other_token = await provisioning_service.create_machine(
        db_session, other_user.id, "other-machine"
    )
    other_ctx = FakeContext(headers={"authorization": f"Bearer {other_token}"})
    result = await studio_claim_task(created["id"], other_ctx)
    assert result["error_code"] == "already_claimed"


async def test_update_task_rejects_stale_version(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_task(str(project.id), "Rename me", auth_ctx)
    result = await studio_update_task(
        created["id"], expected_version=999, ctx=auth_ctx, title="New title"
    )
    assert result["error_code"] == "version_conflict"


async def test_update_task_applies_new_title(auth_ctx: FakeContext, project: ProjectModel) -> None:
    created = await studio_create_task(str(project.id), "Rename me", auth_ctx)
    result = await studio_update_task(
        created["id"], expected_version=created["version"], ctx=auth_ctx, title="New title"
    )
    assert result["title"] == "New title"
