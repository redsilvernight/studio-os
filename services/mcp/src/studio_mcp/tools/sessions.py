from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import idempotency as idempotency_service
from studio_api.services import sessions as sessions_service
from studio_api.services.authz import Principal
from studio_contracts.sessions import WorkSessionCreate

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_session(work_session: WorkSessionModel) -> dict[str, Any]:
    return {
        "id": str(work_session.id),
        "task_id": str(work_session.task_id),
        "machine_id": str(work_session.machine_id),
        "agent_id": str(work_session.agent_id) if work_session.agent_id else None,
        "started_at": work_session.started_at.isoformat(),
        "ended_at": work_session.ended_at.isoformat() if work_session.ended_at else None,
    }


async def studio_get_sessions(ctx: Context, task_id: str | None = None) -> dict[str, Any]:
    """List work sessions, optionally filtered by task_id (UUID string)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_task_id = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task_id = parsed
        work_sessions = await sessions_service.list_sessions(
            session, principal, task_id=parsed_task_id
        )
        return {"sessions": [_compact_session(s) for s in work_sessions]}

    return await run_tool(ctx, _handler)


async def studio_start_session(
    task_id: str, ctx: Context, agent_id: str | None = None, idempotency_key: str | None = None
) -> dict[str, Any]:
    """Start a work session on a task for the caller's machine. Pass a
    caller-generated `idempotency_key` when this call might be retried —
    replaying the same key with the same arguments returns the original
    session instead of starting a second one; the same key with different
    arguments fails with `idempotency_key_payload_mismatch` (DEC-0027)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_task_id = parse_uuid(task_id, "task_id")
        if isinstance(parsed_task_id, dict):
            return parsed_task_id
        parsed_agent_id = None
        if agent_id is not None:
            parsed = parse_uuid(agent_id, "agent_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_agent_id = parsed
        # Ahead of `run_idempotent_dict`'s replay short-circuit — see
        # `routers/tasks.py::create_task` for why (DEC-0036).
        await sessions_service.authorize_start(session, principal, parsed_task_id)

        async def _create() -> dict[str, Any]:
            work_session = await sessions_service.start_session(
                session,
                principal,
                WorkSessionCreate(
                    task_id=parsed_task_id,
                    machine_id=principal.machine.id,
                    agent_id=parsed_agent_id,
                ),
            )
            return _compact_session(work_session)

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {"task_id": task_id, "agent_id": agent_id},
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_start_session", request_hash, _create
        )

    return await run_tool(ctx, _handler)


async def studio_end_session(session_id: str, ctx: Context) -> dict[str, Any]:
    """End a work session by id (UUID string)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(session_id, "session_id")
        if isinstance(parsed, dict):
            return parsed
        work_session = await sessions_service.end_session(session, principal, parsed)
        return _compact_session(work_session)

    return await run_tool(ctx, _handler)
