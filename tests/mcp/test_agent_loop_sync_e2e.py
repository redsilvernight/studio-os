"""AIB L4 E2E: agent A (machine 1) claims a task, then closes with
`coordination.handoff`; agent B (machine 2) resumes through
`studio_start_work` / `studio_sync` and receives the signal bounded, once,
with no duplicate on replay. Real Postgres through the shared savepoint
fixtures."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.claims import studio_claim_resource
from studio_mcp.tools.handoff import studio_handoff
from studio_mcp.tools.start_work import studio_start_work
from studio_mcp.tools.sync import studio_sync
from studio_mcp.tools.tasks import studio_create_task, studio_get_task

from tests.mcp.conftest import FakeContext


def _dump(result: Any) -> dict[str, Any]:
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


def _handoffs(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        i["coordination"]
        for i in block["items"]
        if i["why"] == "coordination" and i["coordination"]["intent"] == "handoff"
    ]


async def test_handoff_signal_reaches_agent_b_on_another_machine_once(
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    project: ProjectModel,
    agent: AgentModel,
    other_machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    other_model, _ = other_machine
    agent_b = AgentModel(machine_id=other_model.id, display_name="agent-b", agent_kind="")
    db_session.add(agent_b)
    await db_session.flush()

    task = await studio_create_task(str(project.id), "Loop A to B", auth_ctx)
    a = await studio_start_work(str(project.id), str(agent.id), auth_ctx, task_id=task["id"])
    assert "error_code" not in a
    session_a = a["session"]["id"]

    claim = await studio_claim_resource(
        str(project.id),
        "src/loop.py",
        "file",
        600,
        auth_ctx,
        task_id=task["id"],
        agent_id=str(agent.id),
    )
    assert "error_code" not in claim

    current = await studio_get_task(task["id"], auth_ctx)
    body: dict[str, Any] = {
        "expected_version": current["version"],
        "task_status": "blocked",
        "agent_id": str(agent.id),
        "summary": "DONE step 1\nNEXT step 2",
        "coordination_text": "reprendre a l etape 2",
        "idempotency_key": "e2e-handoff-a",
    }
    closed = await studio_handoff(str(project.id), session_a, auth_ctx, **body)
    assert "error_code" not in closed
    event_id = closed["coordination_event_id"]
    assert event_id is not None

    # Agent B: another machine, zero history.
    b = await studio_start_work(
        str(project.id), str(agent_b.id), other_auth_ctx, task_id=task["id"]
    )
    assert "error_code" not in b
    session_b = b["session"]["id"]

    pulled = _dump(await studio_sync(other_auth_ctx, session_id=session_b))
    assert [s["event_id"] for s in _handoffs(pulled)] == [event_id]
    assert len(json.dumps(pulled)) < 4000

    # Ack, then replay the same ack: nothing new, no duplicate delivery.
    acked = _dump(
        await studio_sync(other_auth_ctx, session_id=session_b, ack=pulled["next_cursor"])
    )
    assert _handoffs(acked) == []
    replay = _dump(
        await studio_sync(other_auth_ctx, session_id=session_b, ack=pulled["next_cursor"])
    )
    assert replay == acked

    # Replaying A's handoff (same key) returns the stored result, emits nothing new.
    again = await studio_handoff(str(project.id), session_a, auth_ctx, **body)
    assert again == closed
    after = _dump(await studio_sync(other_auth_ctx, session_id=session_b, ack=acked["next_cursor"]))
    assert _handoffs(after) == []
