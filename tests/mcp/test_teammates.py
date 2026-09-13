from __future__ import annotations

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.claims import studio_claim_resource
from studio_mcp.tools.tasks import studio_claim_task, studio_create_task
from studio_mcp.tools.teammates import studio_get_teammate_activity

from tests.mcp.conftest import FakeContext


async def test_teammate_activity_lists_machine_with_claimed_task(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    task = await studio_create_task(str(project.id), "Claimed task", auth_ctx)
    await studio_claim_task(task["id"], auth_ctx)

    result = await studio_get_teammate_activity(str(project.id), auth_ctx)
    assert any(t["machine_id"] == str(machine_model.id) for t in result["teammates"])


async def test_teammate_activity_lists_machine_with_active_claim(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    await studio_claim_resource(str(project.id), "docs/plan.md", "file", 600, auth_ctx)

    result = await studio_get_teammate_activity(str(project.id), auth_ctx)
    assert any(t["machine_id"] == str(machine_model.id) for t in result["teammates"])


async def test_teammate_activity_empty_for_idle_project(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_get_teammate_activity(str(project.id), auth_ctx)
    assert result["teammates"] == []


async def test_teammate_activity_rejects_bad_uuid(auth_ctx: FakeContext) -> None:
    result = await studio_get_teammate_activity("not-a-uuid", auth_ctx)
    assert result["error_code"] == "invalid_argument"
