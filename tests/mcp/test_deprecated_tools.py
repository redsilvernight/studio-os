from __future__ import annotations

from typing import Any

import pytest
from studio_mcp.access_registry import MCP_ACCESS
from studio_mcp.deprecation import REPLACED_BY, SUNSET, deprecated, deprecation_notice
from studio_mcp.server import create_server
from studio_mcp.tool_profiles import SESSION_TOOL_PROFILE

# DEC-0186: redundant session/claim tools stay callable until SUNSET, labelled
# in `tools/list` and in every successful answer. Pure metadata: no database.


@pytest.mark.asyncio
async def test_deprecated_tools_are_labelled_in_tools_list() -> None:
    tools = {tool.name: tool for tool in await create_server().list_tools()}
    for name, replacement in REPLACED_BY.items():
        description = tools[name].description or ""
        assert description.startswith("DEPRECATED"), name
        assert SUNSET in description and replacement in description, name
    for name in set(tools) - set(REPLACED_BY):
        assert not (tools[name].description or "").startswith("DEPRECATED"), name


def test_replacements_are_exposed_and_not_themselves_deprecated() -> None:
    for name, replacement in REPLACED_BY.items():
        assert name in MCP_ACCESS
        assert replacement in MCP_ACCESS
        assert replacement not in REPLACED_BY
        assert replacement in SESSION_TOOL_PROFILE
        assert name not in SESSION_TOOL_PROFILE


@pytest.mark.asyncio
async def test_successful_answer_carries_the_notice() -> None:
    async def tool(task_id: str) -> dict[str, Any]:
        return {"id": task_id}

    wrapped = deprecated("studio_claim_task", tool)
    assert await wrapped("t1") == {
        "id": "t1",
        "deprecation": deprecation_notice("studio_claim_task"),
    }
    assert deprecation_notice("studio_claim_task") == {
        "replaced_by": "studio_start_work",
        "sunset": SUNSET,
    }


@pytest.mark.asyncio
async def test_error_answer_is_left_untouched() -> None:
    error = {"error_code": "already_claimed", "message": "held"}

    async def tool() -> dict[str, Any]:
        return error

    assert await deprecated("studio_claim_task", tool)() == error
