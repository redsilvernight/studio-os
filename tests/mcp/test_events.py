from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import provisioning as provisioning_service
from studio_mcp.tools.events import studio_emit_event, studio_get_recent_changes

from tests.mcp.conftest import FakeContext


async def test_emit_event_records_caller_machine(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    result = await studio_emit_event(
        str(project.id),
        "task.started",
        "user",
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
        str(project.id), "not.a.real.event", "user", str(machine_model.owner_user_id), auth_ctx
    )
    assert result["error_code"] == "invalid_event_type"


async def test_emit_event_rejects_machine_id_of_another_machine(
    auth_ctx: FakeContext,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    other_user = await provisioning_service.create_user(
        db_session, "Other User", f"other-{machine_model.id}@example.test", "developer"
    )
    other_machine, _ = await provisioning_service.create_machine(
        db_session, other_user.id, "other-machine"
    )
    result = await studio_emit_event(
        str(project.id),
        "task.started",
        "user",
        str(machine_model.owner_user_id),
        auth_ctx,
        machine_id=str(other_machine.id),
    )
    assert result["error_code"] == "machine_id_mismatch"


async def test_emit_event_rejects_agent_not_attached_to_authenticated_machine(
    auth_ctx: FakeContext,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    other_user = await provisioning_service.create_user(
        db_session, "Other User", "other-agent-owner@example.test", "developer"
    )
    other_machine, _ = await provisioning_service.create_machine(
        db_session, other_user.id, "other-machine"
    )
    foreign_agent = AgentModel(
        machine_id=other_machine.id, display_name="other-agent", agent_kind="claude_code"
    )
    db_session.add(foreign_agent)
    await db_session.flush()
    await db_session.refresh(foreign_agent)

    result = await studio_emit_event(
        str(project.id), "task.started", "agent", str(foreign_agent.id), auth_ctx
    )
    assert result["error_code"] == "actor_not_owned"


async def test_emit_event_accepts_agent_attached_to_authenticated_machine(
    auth_ctx: FakeContext,
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    result = await studio_emit_event(
        str(project.id), "task.started", "agent", str(agent.id), auth_ctx
    )
    assert result["event_type"] == "task.started"


async def test_get_recent_changes_lists_emitted_event(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    emitted = await studio_emit_event(
        str(project.id), "task.started", "user", str(machine_model.owner_user_id), auth_ctx
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


async def test_emit_event_accepts_caller_supplied_event_id(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    """DEC-0027: studio_emit_event must accept the caller's own stable
    event_id (offline queue replay) rather than always generating its own —
    events_service.create_event is already idempotent on event_id."""
    machine_model, _ = machine
    stable_id = "11111111-1111-4111-8111-111111111111"
    result = await studio_emit_event(
        str(project.id),
        "task.started",
        "user",
        str(machine_model.owner_user_id),
        auth_ctx,
        event_id=stable_id,
    )
    assert result["event_id"] == stable_id


async def test_emit_event_replay_same_event_id_creates_no_duplicate(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    stable_id = "22222222-2222-4222-8222-222222222222"
    first = await studio_emit_event(
        str(project.id),
        "task.started",
        "user",
        str(machine_model.owner_user_id),
        auth_ctx,
        event_id=stable_id,
        payload={"attempt": 1},
    )
    second = await studio_emit_event(
        str(project.id),
        "task.started",
        "user",
        str(machine_model.owner_user_id),
        auth_ctx,
        event_id=stable_id,
        payload={"attempt": 2},
    )
    assert second["event_id"] == first["event_id"]
    assert second["payload"] == first["payload"] == {"attempt": 1}

    result = await studio_get_recent_changes(auth_ctx, project_id=str(project.id))
    matches = [e for e in result["events"] if e["event_id"] == stable_id]
    assert len(matches) == 1
