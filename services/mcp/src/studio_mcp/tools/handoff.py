from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import handoff as handoff_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import Principal
from studio_contracts.handoff import HandoffRequest
from studio_contracts.tasks import TaskStatus, TaskUpdate

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


async def studio_handoff(
    project_id: str,
    session_id: str,
    expected_version: int,
    ctx: Context,
    task_status: str | None = None,
    agent_id: str | None = None,
    summary: str | None = None,
    ai_work_status: str | None = None,
    changed_files: list[str] | None = None,
    tests_run: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Close a work session in one call (L3 handoff). `project_id`,
    `session_id` (UUID strings) and `expected_version` are required.
    `task_status` (e.g. "completed", "blocked") optionally updates the
    task. `agent_id` + `summary` optionally logs an AI work entry linked
    to the session. `agent_id` must belong to the caller's machine.
    Caller-generated `idempotency_key` makes the call replay-safe: the
    same key returns the original result instead of running the composite
    again — a duplicate call returns the original result without a second
    status update, duplicate claim releases, duplicate AI work entry, or
    second session end. Compact response: ids + statuses only. Requires a
    writer role."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_project = parse_uuid(project_id, "project_id")
        if isinstance(parsed_project, dict):
            return parsed_project
        parsed_session = parse_uuid(session_id, "session_id")
        if isinstance(parsed_session, dict):
            return parsed_session
        parsed_agent = None
        if agent_id is not None:
            parsed = parse_uuid(agent_id, "agent_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_agent = parsed

        task_update = None
        if task_status is not None:
            task_update = TaskUpdate(status=TaskStatus(task_status))

        request = HandoffRequest(
            project_id=parsed_project,
            session_id=parsed_session,
            expected_version=expected_version,
            task_status=task_update,
            agent_id=parsed_agent,
            summary=summary,
            ai_work_status=ai_work_status,
            changed_files=changed_files,
            tests_run=tests_run,
        )

        async def _create() -> dict[str, Any]:
            result = await handoff_service.handoff(session, principal, request)
            return result.model_dump(mode="json")  # type: ignore[no-any-return]

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {
                    "project_id": project_id,
                    "session_id": session_id,
                    "expected_version": expected_version,
                    "task_status": task_status,
                    "agent_id": agent_id,
                    "summary": summary,
                    "ai_work_status": ai_work_status,
                    "changed_files": changed_files,
                    "tests_run": tests_run,
                },
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_handoff", request_hash, _create
        )

    return await run_tool(ctx, _handler)