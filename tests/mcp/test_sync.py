"""`studio_sync` (C2/DEC-0157) over MCP: same bounded resync as
`GET /sync`, same authority — per-session ack cursor, deterministic `why`
filter, replay-safe by cursor. Real Postgres through the shared savepoint
fixtures."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.sync import studio_sync
from studio_mcp.tools.tasks import studio_create_task

from tests.mcp.conftest import FakeContext


def dump(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    assert isinstance(result, dict)
    return result


async def test_sync_tool_returns_bounded_result_and_replays(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Sync me", auth_ctx)

    first = dump(await studio_sync(auth_ctx, agent_id=str(agent.id), task_id=task["id"]))
    assert first["items"] == []
    assert first["overflow"] == {}
    assert first["resync"] is False

    again = dump(await studio_sync(auth_ctx, agent_id=str(agent.id), task_id=task["id"]))
    assert again == first


async def test_sync_tool_rejects_bad_uuid(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Sync me", auth_ctx)
    result = dump(
        await studio_sync(
            auth_ctx,
            agent_id=str(agent.id),
            task_id=task["id"],
            session_id="nope",
        )
    )
    assert result["error_code"] == "invalid_argument"


async def test_sync_tool_reports_unknown_session(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Sync me", auth_ctx)
    result = dump(
        await studio_sync(
            auth_ctx,
            agent_id=str(agent.id),
            task_id=task["id"],
            session_id=str(uuid.uuid4()),
        )
    )
    assert result["error_code"] == "session_not_found"
