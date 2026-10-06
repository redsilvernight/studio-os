from __future__ import annotations

from typing import Any, cast

from studio_mcp.access_registry import MCP_ACCESS
from studio_mcp.server import mcp
from studio_mcp.tools.sessions import studio_start_session
from studio_mcp.tools.tasks import studio_create_task

from tests.mcp.conftest import FakeContext


def _manager() -> Any:
    return cast(Any, mcp)._tool_manager


def test_all_tools_reject_additional_properties() -> None:
    manager = _manager()
    missing = [
        name
        for name in MCP_ACCESS
        if manager.get_tool(name) is None
        or manager.get_tool(name).parameters.get("additionalProperties") is not False
    ]
    assert missing == []


async def test_handoff_rejects_unknown_status_argument(auth_ctx: FakeContext) -> None:
    manager = _manager()
    tool = manager.get_tool("studio_handoff")
    assert tool is not None
    result = await tool.run(
        {
            "project_id": "00000000-0000-0000-0000-000000000000",
            "session_id": "00000000-0000-0000-0000-000000000001",
            "status": "completed",
        },
        auth_ctx,
    )
    assert result["error_code"] == "invalid_argument"
    assert "status" in result["unknown_arguments"]
    assert "task_status" in result["valid_arguments"]
    assert "status" not in result["valid_arguments"]


async def test_handoff_unknown_argument_rejected_before_db(
    readonly_auth_ctx: FakeContext,
) -> None:
    manager = _manager()
    result = await manager.call_tool(
        "studio_handoff",
        {
            "project_id": "00000000-0000-0000-0000-000000000000",
            "session_id": "00000000-0000-0000-0000-000000000001",
            "status": "completed",
        },
        readonly_auth_ctx,
    )
    assert result["error_code"] == "invalid_argument"
    assert result["unknown_arguments"] == ["status"]


async def test_get_task_rejects_unknown_argument(auth_ctx: FakeContext) -> None:
    manager = _manager()
    result = await manager.call_tool(
        "studio_get_task",
        {"task_id": "00000000-0000-0000-0000-000000000000", "verbose": True},
        auth_ctx,
    )
    assert result["error_code"] == "invalid_argument"
    assert result["unknown_arguments"] == ["verbose"]


async def test_handoff_valid_call_still_succeeds(
    auth_ctx: FakeContext, project: Any, agent: Any
) -> None:
    task = await studio_create_task(str(project.id), "Strict ok", auth_ctx)
    started = await studio_start_session(task["id"], auth_ctx)
    manager = _manager()
    result = await manager.call_tool(
        "studio_handoff",
        {"project_id": str(project.id), "session_id": started["id"]},
        auth_ctx,
    )
    assert "error_code" not in result
