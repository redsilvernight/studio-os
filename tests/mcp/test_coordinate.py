"""`studio_coordinate` (C3/DEC-0157) over MCP: same validated emission as
`POST /coordination`; recipients read through `studio_sync` only."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.coordination import studio_coordinate
from studio_mcp.tools.start_work import studio_start_work
from studio_mcp.tools.tasks import studio_create_task

from tests.mcp.conftest import FakeContext


def dump(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    assert isinstance(result, dict)
    return result


async def _session(ctx: FakeContext, project: ProjectModel, agent: AgentModel) -> tuple[str, str]:
    task = await studio_create_task(str(project.id), "Coord", ctx)
    started = dump(await studio_start_work(str(project.id), str(agent.id), ctx, task_id=task["id"]))
    return task["id"], started["session"]["id"]


async def test_emit_and_replay(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task_id, session_id = await _session(auth_ctx, project, agent)
    kwargs: dict[str, Any] = {
        "from_session_id": session_id,
        "intent": "heads_up",
        "task_id": task_id,
        "text": "touching db.py",
        "paths": ["db.py"],
        "event_id": str(uuid.uuid4()),
    }
    first = dump(await studio_coordinate(ctx=auth_ctx, **kwargs))
    assert first["event_type"] == "coordination.heads_up"
    assert dump(await studio_coordinate(ctx=auth_ctx, **kwargs)) == first


async def test_rejects_bad_input(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task_id, session_id = await _session(auth_ctx, project, agent)
    base: dict[str, Any] = {"from_session_id": session_id, "task_id": task_id, "text": "hi"}
    bad_intent = dump(await studio_coordinate(ctx=auth_ctx, intent="chat", **base))
    assert bad_intent["error_code"] == "invalid_coordination"
    too_long = dump(
        await studio_coordinate(ctx=auth_ctx, intent="question", **{**base, "text": "x" * 281})
    )
    assert too_long["error_code"] == "invalid_coordination"
    bad_uuid = dump(
        await studio_coordinate(ctx=auth_ctx, intent="question", **{**base, "task_id": "nope"})
    )
    assert bad_uuid["error_code"] == "invalid_argument"
