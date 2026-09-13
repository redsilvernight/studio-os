from __future__ import annotations

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.events import studio_emit_event, studio_get_recent_changes

from tests.mcp.conftest import FakeContext


async def test_emit_event_records_caller_machine(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    result = await studio_emit_event(
        str(project.id),
        "task.started",
        "agent",
        str(machine_model.owner_user_id),
        auth_ctx,
    )
    assert result["event_type"] == "task.started"
    assert result["project_id"] == str(project.id)


async def test_emit_event_rejects_unknown_event_type(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    result = await studio_emit_event(
        str(project.id), "not.a.real.event", "agent", str(machine_model.owner_user_id), auth_ctx
    )
    assert result["error_code"] == "invalid_event_type"


async def test_get_recent_changes_lists_emitted_event(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    emitted = await studio_emit_event(
        str(project.id), "task.started", "agent", str(machine_model.owner_user_id), auth_ctx
    )
    result = await studio_get_recent_changes(auth_ctx, project_id=str(project.id))
    assert any(e["event_id"] == emitted["event_id"] for e in result["events"])


async def test_get_recent_changes_rejects_bad_since(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_get_recent_changes(
        auth_ctx, project_id=str(project.id), since="not-a-date"
    )
    assert result["error_code"] == "invalid_argument"
