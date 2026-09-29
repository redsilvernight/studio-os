from __future__ import annotations

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.sessions import studio_end_session, studio_get_sessions, studio_start_session
from studio_mcp.tools.tasks import studio_create_task

from tests.mcp.conftest import FakeContext


async def test_start_and_end_session(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    task = await studio_create_task(str(project.id), "Do the thing", auth_ctx)

    started = await studio_start_session(task["id"], auth_ctx)
    assert started["task_id"] == task["id"]
    assert started["machine_id"] == str(machine_model.id)
    assert started["ended_at"] is None

    ended = await studio_end_session(started["id"], auth_ctx)
    assert ended["ended_at"] is not None


async def test_start_session_can_return_compact_response(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    task = await studio_create_task(str(project.id), "Compact session", auth_ctx)
    started = await studio_start_session(task["id"], auth_ctx, verbose=False)
    assert set(started) == {"id", "task_id", "agent_id", "status"}


async def test_start_session_rejects_unknown_task(auth_ctx: FakeContext) -> None:
    result = await studio_start_session("00000000-0000-0000-0000-000000000000", auth_ctx)
    assert result["error_code"] == "invalid_reference"


async def test_end_session_rejects_unknown_session(auth_ctx: FakeContext) -> None:
    result = await studio_end_session("00000000-0000-0000-0000-000000000000", auth_ctx)
    assert result["error_code"] == "error"


async def test_get_sessions_filters_by_task(auth_ctx: FakeContext, project: ProjectModel) -> None:
    task = await studio_create_task(str(project.id), "Filtered task", auth_ctx)
    started = await studio_start_session(task["id"], auth_ctx)
    result = await studio_get_sessions(auth_ctx, task_id=task["id"])
    assert any(s["id"] == started["id"] for s in result["sessions"])


async def test_start_session_idempotency_key_replay_starts_no_second_session(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    """DEC-0027: a replayed studio_start_session call must not start a second
    work session for the same retried request."""
    task = await studio_create_task(str(project.id), "Idempotent session task", auth_ctx)
    first = await studio_start_session(task["id"], auth_ctx, idempotency_key="mcp-session-key-1")
    second = await studio_start_session(task["id"], auth_ctx, idempotency_key="mcp-session-key-1")
    assert second["id"] == first["id"]

    result = await studio_get_sessions(auth_ctx, task_id=task["id"])
    assert len(result["sessions"]) == 1


async def test_start_session_idempotency_distinguishes_compact_response(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    task = await studio_create_task(str(project.id), "Session response shape", auth_ctx)
    await studio_start_session(task["id"], auth_ctx, idempotency_key="mcp-session-shape")
    mismatch = await studio_start_session(
        task["id"],
        auth_ctx,
        idempotency_key="mcp-session-shape",
        verbose=False,
    )
    assert mismatch["error_code"] == "idempotency_key_payload_mismatch"


async def test_get_sessions_filters_by_agent_and_open_state(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Open filter task", auth_ctx)
    started = await studio_start_session(task["id"], auth_ctx, agent_id=str(agent.id))
    await studio_end_session(started["id"], auth_ctx)

    still_open = await studio_get_sessions(auth_ctx, task_id=task["id"], open_only=True)
    assert still_open["sessions"] == []

    by_agent = await studio_get_sessions(auth_ctx, task_id=task["id"], agent_id=str(agent.id))
    assert [s["id"] for s in by_agent["sessions"]] == [started["id"]]
