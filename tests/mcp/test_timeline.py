from __future__ import annotations

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.events import studio_emit_event
from studio_mcp.tools.timeline import studio_get_timeline

from tests.mcp.conftest import FakeContext


async def test_get_timeline_empty(auth_ctx: FakeContext, project: ProjectModel) -> None:
    result = await studio_get_timeline(str(project.id), auth_ctx)
    assert result["days"] == []


async def test_get_timeline_includes_emitted_event(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    emitted = await studio_emit_event(
        str(project.id),
        "task.created",
        "system",
        str(machine_model.id),
        auth_ctx,
    )
    assert "error_code" not in emitted

    result = await studio_get_timeline(str(project.id), auth_ctx)
    assert len(result["days"]) == 1
    event_types = [e["event_type"] for e in result["days"][0]["events"]]
    assert "task.created" in event_types


async def test_get_timeline_rejects_invalid_project_id(auth_ctx: FakeContext) -> None:
    result = await studio_get_timeline("not-a-uuid", auth_ctx)
    assert result["error_code"] == "invalid_argument"


async def test_get_timeline_rejects_invalid_since(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_get_timeline(str(project.id), auth_ctx, since="not-a-date")
    assert result["error_code"] == "invalid_argument"
