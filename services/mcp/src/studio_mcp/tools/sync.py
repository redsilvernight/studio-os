from __future__ import annotations

from mcp.server.mcpserver import Context
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import sync as sync_service
from studio_api.services.authz import Principal
from studio_contracts.project_context import DEFAULT_MAX_CHARS
from studio_contracts.sync import (
    SYNC_DEFAULT_LIMIT,
    SyncResult,
)

from studio_mcp.errors import McpError, run_tool
from studio_mcp.util import parse_uuid


async def studio_sync(
    ctx: Context,
    session_id: str | None = None,
    agent_id: str | None = None,
    task_id: str | None = None,
    ack: int | None = None,
    files: list[str] | None = None,
    limit: int = SYNC_DEFAULT_LIMIT,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> SyncResult | McpError:
    """Resynchronise one work session (C2): what changed since the last sync
    that concerns this work, as a compact bounded answer. `session_id`
    selects the session (its task is used, its stored cursor is the default
    start); without it, `agent_id` + `task_id` is a stateless lookup
    persisting nothing. `ack` acknowledges the highest processed `seq`: the
    stored cursor advances monotonically to it (a stale replay changes
    nothing), and `next_cursor` in the answer is what to ack next. `files`
    scopes claim overlap to declared paths. `limit`/`max_chars` bound the
    answer (same budget as `prepare_context`); the remainder surfaces as
    per-`why` `overflow` counters, and a truncated scan sets `resync` (see
    `prepare_context` — raw history is never dumped). Replay-safe by cursor:
    the same `ack` returns the same answer, never a duplicate effect."""

    async def _handler(session: AsyncSession, principal: Principal) -> SyncResult | McpError:
        parsed_session = None
        if session_id is not None:
            parsed = parse_uuid(session_id, "session_id")
            if isinstance(parsed, dict):
                return McpError.model_validate(parsed)
            parsed_session = parsed
        parsed_agent = None
        if agent_id is not None:
            parsed = parse_uuid(agent_id, "agent_id")
            if isinstance(parsed, dict):
                return McpError.model_validate(parsed)
            parsed_agent = parsed
        parsed_task = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return McpError.model_validate(parsed)
            parsed_task = parsed
        return await sync_service.sync(
            session,
            principal,
            session_id=parsed_session,
            agent_id=parsed_agent,
            task_id=parsed_task,
            ack=ack,
            files=files,
            limit=limit,
            max_chars=max_chars,
        )

    raw = await run_tool(ctx, _handler)
    if isinstance(raw, dict):  # auth / HTTPException / IntegrityError envelopes
        try:
            return McpError.model_validate(raw)
        except ValidationError:
            return McpError(error_code="error", message=str(raw))
    return raw
