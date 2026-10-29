from __future__ import annotations

import json

from sqlalchemy.exc import OperationalError
from studio_contracts.tasks import TaskCreate
from studio_mcp.errors import run_tool

from tests.mcp.conftest import FakeContext


async def test_service_validation_error_is_bounded_and_does_not_echo_input(
    auth_ctx: FakeContext,
) -> None:
    async def handler(session, principal):
        return TaskCreate.model_validate({"project_id": "secret-input"})

    result = await run_tool(auth_ctx, handler)
    assert result["error_code"] == "invalid_argument"
    assert len(result["fields"]) <= 3
    assert "secret-input" not in json.dumps(result)


async def test_database_error_is_structured_without_raw_connection_details(
    auth_ctx: FakeContext,
) -> None:
    async def handler(session, principal):
        raise OperationalError("secret-sql", {}, Exception("private-connection"))

    result = await run_tool(auth_ctx, handler)
    assert result["error_code"] == "service_unavailable"
    assert "private-connection" not in json.dumps(result)
    assert "secret-sql" not in json.dumps(result)


async def test_oversized_service_error_is_explicitly_truncated(auth_ctx: FakeContext) -> None:
    async def handler(session, principal):
        return {"error_code": "invalid_status", "message": "unknown " * 100000, "server_version": 7}

    result = await run_tool(auth_ctx, handler)
    assert result["error_code"] == "invalid_status"
    assert result["server_version"] == 7
    assert result["details_truncated"] is True
    assert len(json.dumps(result)) < 8192


async def test_unexpected_service_error_is_logged_without_leaking_exception_text(
    auth_ctx: FakeContext,
) -> None:
    async def handler(session, principal):
        raise RuntimeError("private-value")

    result = await run_tool(auth_ctx, handler)
    assert result["error_code"] == "internal_error"
    assert "private-value" not in json.dumps(result)
