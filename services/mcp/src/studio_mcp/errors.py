from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from mcp.server.mcpserver import Context
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.session import get_session_factory
from studio_api.services.authz import Principal, load_principal
from studio_api.services.launch_credentials import ensure_tool_allowed

from studio_mcp.auth import McpAuthError, authenticate

ToolHandler = Callable[[AsyncSession, Principal], Awaitable[Any]]
logger = logging.getLogger(__name__)


def bounded_error(error: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(error, ensure_ascii=False, default=str).encode("utf-8")) <= 8192:
        return error
    compact = {
        "error_code": str(error.get("error_code", "error"))[:80],
        "message": str(error.get("message", ""))[:1000],
        "details_truncated": True,
    }
    if isinstance(error.get("server_version"), int):
        compact["server_version"] = error["server_version"]
    return compact


def validation_error(exc: ValidationError) -> dict[str, Any]:
    return {
        "error_code": "invalid_argument",
        "message": "invalid tool arguments",
        "fields": [
            {
                "field": ".".join(str(part) for part in error["loc"])[:100],
                "type": str(error["type"])[:80],
            }
            for error in exc.errors(include_input=False, include_context=False, include_url=False)[
                :3
            ]
        ],
    }


class McpError(BaseModel):
    """In-band error arm for P8 structured outputs (DEC-0048: no second
    taxonomy — same `error_code` vocabulary as the services/HTTP layer).
    `extra="allow"` preserves machine-readable extras the services already
    emit (`server_version`, `unsatisfied`, `level`, ...) instead of dropping
    them at the protocol boundary; `message` defaults so armless envelopes
    (e.g. `forbidden`) still validate."""

    model_config = ConfigDict(extra="allow")

    error_code: str
    message: str = ""


def _http_exception_to_dict(exc: HTTPException) -> dict[str, Any]:
    detail = exc.detail
    if isinstance(detail, dict):
        return bounded_error(detail)
    return bounded_error({"error_code": "error", "message": str(detail)})


def _tool_name(handler: Callable[..., Any]) -> str | None:
    """Tools define their handler as a closure inside the tool function, so
    its qualified name starts with the registered tool name."""
    qualname = getattr(handler, "__qualname__", "")
    head, sep, _ = qualname.partition(".<locals>.")
    return head if sep else None


async def run_tool[T](
    ctx: Context, handler: Callable[[AsyncSession, Principal], Awaitable[T]]
) -> T:
    """Every write/read tool goes through this: authenticate the caller
    (DEC-0023), open one session for the call, and translate any error a
    `studio_api.services.*` function raises into the same machine-readable
    shape `{error_code, message, ...}` — never a raw stack trace
    (.claude/rules/mcp-tools.md). Auth and transport failures answer plain
    error dicts regardless of `T`; P8 tools normalize those to their
    declared error model themselves."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            machine = await authenticate(ctx, session)
            ensure_tool_allowed(machine, _tool_name(handler))
            principal = await load_principal(session, machine)
            result = await handler(session, principal)
            if isinstance(result, dict) and "error_code" in result:
                return bounded_error(result)  # type: ignore[return-value]
            if isinstance(result, McpError):
                return McpError.model_validate(bounded_error(result.model_dump()))  # type: ignore[return-value]
            return result
        except McpAuthError as exc:
            return exc.to_dict()  # type: ignore[return-value]
        except HTTPException as exc:
            return _http_exception_to_dict(exc)  # type: ignore[return-value]
        except ValidationError as exc:
            await session.rollback()
            return validation_error(exc)  # type: ignore[return-value]
        except ImportError:
            # A lazily imported service module that is not deployed yet (e.g.
            # the Roadmap service before P3 converges) must answer a structured
            # error, never a raw stack trace (.claude/rules/mcp-tools.md).
            await session.rollback()
            logger.exception("MCP service module unavailable")
            return {  # type: ignore[return-value]
                "error_code": "service_unavailable",
                "message": "service module unavailable",
            }
        except IntegrityError:
            # A caller-supplied id (task_id, project_id, ...) that
            # doesn't exist — the FK constraint is the only thing that caught
            # it, since services/*.py trusts callers the same way the HTTP
            # routers do. (agent_id no longer reaches this path: CC-1/DEC-0045
            # validates it in-service as 409 actor_not_owned.) Roll back so the
            # the session's transaction open, then report it plainly rather
            # than crashing the tool call.
            await session.rollback()
            return {  # type: ignore[return-value]
                "error_code": "invalid_reference",
                "message": "one of the referenced ids does not exist",
            }
        except SQLAlchemyError:
            await session.rollback()
            logger.exception("MCP database operation failed")
            return {  # type: ignore[return-value]
                "error_code": "service_unavailable",
                "message": "database operation unavailable",
            }
        except Exception:
            await session.rollback()
            logger.exception("Unexpected MCP service failure")
            return {  # type: ignore[return-value]
                "error_code": "internal_error",
                "message": "unexpected service failure",
            }
