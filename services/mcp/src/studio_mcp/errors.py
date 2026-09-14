from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from mcp.server.mcpserver import Context
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.session import get_session_factory
from studio_api.services.authz import Principal, load_principal

from studio_mcp.auth import McpAuthError, authenticate

ToolHandler = Callable[[AsyncSession, Principal], Awaitable[dict[str, Any]]]


def _http_exception_to_dict(exc: HTTPException) -> dict[str, Any]:
    detail = exc.detail
    if isinstance(detail, dict):
        return detail
    return {"error_code": "error", "message": str(detail)}


async def run_tool(ctx: Context, handler: ToolHandler) -> dict[str, Any]:
    """Every write/read tool goes through this: authenticate the caller
    (DEC-0023), open one session for the call, and translate any error a
    `studio_api.services.*` function raises into the same machine-readable
    shape `{error_code, message, ...}` — never a raw stack trace
    (.claude/rules/mcp-tools.md)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            machine = await authenticate(ctx, session)
            principal = await load_principal(session, machine)
            return await handler(session, principal)
        except McpAuthError as exc:
            return exc.to_dict()
        except HTTPException as exc:
            return _http_exception_to_dict(exc)
        except IntegrityError:
            # A caller-supplied id (task_id, project_id, agent_id, ...) that
            # doesn't exist — the FK constraint is the only thing that caught
            # it, since services/*.py trusts callers the same way the HTTP
            # routers do. Roll back so the failed insert/update doesn't hold
            # the session's transaction open, then report it plainly rather
            # than crashing the tool call.
            await session.rollback()
            return {
                "error_code": "invalid_reference",
                "message": "one of the referenced ids does not exist",
            }
