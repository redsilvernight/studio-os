from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import idempotency as idempotency_service
from studio_api.services import start_work as start_work_service
from studio_api.services.authz import Principal
from studio_api.settings import get_settings
from studio_contracts.project_context import DEFAULT_LIMIT, DEFAULT_MAX_CHARS
from studio_contracts.start_work import StartWorkRequest

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


async def studio_start_work(
    project_id: str,
    agent_id: str,
    ctx: Context,
    task_id: str | None = None,
    objective: str | None = None,
    agent_stable_key: str | None = None,
    files: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    max_chars: int = DEFAULT_MAX_CHARS,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Start or resume work on a task in one call (or, without task_id, return
    the project context and candidate tasks without claiming anything).
    `project_id`/`agent_id` (UUID strings) are required and the agent must
    belong to the caller's machine. Caller-generated `idempotency_key` makes
    the call replay-safe: the same key returns the original result instead of
    claiming or starting a second time (DEC-0027/DEC-0159) — even without it,
    a replay never creates a second claim nor a second session."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_project = parse_uuid(project_id, "project_id")
        if isinstance(parsed_project, dict):
            return parsed_project
        parsed_agent = parse_uuid(agent_id, "agent_id")
        if isinstance(parsed_agent, dict):
            return parsed_agent
        parsed_task = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task = parsed
        request = StartWorkRequest(
            project_id=parsed_project,
            agent_id=parsed_agent,
            task_id=parsed_task,
            objective=objective,
            agent_stable_key=agent_stable_key,
            files=files,
            limit=limit,
            max_chars=max_chars,
        )
        # Ahead of `run_idempotent_dict`'s replay short-circuit (DEC-0036).
        await start_work_service.authorize_start_work(session, principal, request)

        async def _create() -> dict[str, Any]:
            result = await start_work_service.start_work(
                session, principal, request, get_settings()
            )
            return result.model_dump(mode="json")

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {
                    "project_id": project_id,
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "objective": objective,
                    "agent_stable_key": agent_stable_key,
                    "files": files,
                    "limit": limit,
                    "max_chars": max_chars,
                },
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_start_work", request_hash, _create
        )

    return await run_tool(ctx, _handler)
