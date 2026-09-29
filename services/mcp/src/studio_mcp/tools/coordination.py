from __future__ import annotations

from mcp.server.mcpserver import Context
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import coordination as coordination_service
from studio_api.services.authz import Principal
from studio_contracts.coordination import (
    CoordinationEmit,
    CoordinationEmitted,
    CoordinationRefs,
)

from studio_mcp.errors import McpError, run_tool
from studio_mcp.util import parse_uuid


async def studio_coordinate(
    from_session_id: str,
    intent: str,
    task_id: str,
    text: str,
    ctx: Context,
    session_id: str | None = None,
    task_ids: list[str] | None = None,
    decision_ids: list[str] | None = None,
    paths: list[str] | None = None,
    in_reply_to: str | None = None,
    event_id: str | None = None,
) -> CoordinationEmitted | McpError:
    """Emit one structured inter-session signal (C3): `intent` is one of
    heads_up, question, blocked_by, handoff. `task_id` is the mandatory
    target (same project as your own session `from_session_id`, not
    completed); `session_id` optionally narrows it to one live session of
    that task. `text` is at most 280 characters; `task_ids`, `decision_ids`
    and `paths` are structured references (at most 5 each); `in_reply_to`
    is an earlier signal's event_id. Recipients read it only through
    `studio_sync` (quoted data, never an instruction); there is no read
    tool. At most 20 signals per emitting session. Pass a stable `event_id`
    when retrying: a replay returns the original signal, no duplicate."""

    async def _handler(
        session: AsyncSession, principal: Principal
    ) -> CoordinationEmitted | McpError:
        parsed: dict[str, object] = {}
        for name, value in (
            ("from_session_id", from_session_id),
            ("task_id", task_id),
            ("session_id", session_id),
            ("in_reply_to", in_reply_to),
            ("event_id", event_id),
        ):
            if value is None:
                parsed[name] = None
                continue
            result = parse_uuid(value, name)
            if isinstance(result, dict):
                return McpError.model_validate(result)
            parsed[name] = result
        try:
            refs = CoordinationRefs(
                task_ids=task_ids or [],  # type: ignore[arg-type]
                decision_ids=decision_ids or [],  # type: ignore[arg-type]
                paths=paths or [],
            )
            body = CoordinationEmit(
                intent=intent,  # type: ignore[arg-type]
                text=text,
                refs=refs,
                **parsed,  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            return McpError(error_code="invalid_coordination", message=str(exc.errors()[0]["msg"]))
        return await coordination_service.emit(session, principal, body)

    raw = await run_tool(ctx, _handler)
    if isinstance(raw, dict):
        try:
            return McpError.model_validate(raw)
        except ValidationError:
            return McpError(error_code="error", message=str(raw))
    return raw
