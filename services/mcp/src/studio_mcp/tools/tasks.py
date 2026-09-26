from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.task import TaskModel
from studio_api.services import idempotency as idempotency_service
from studio_api.services import projects as projects_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal
from studio_contracts.tasks import TaskCreate, TaskStatus, TaskUpdate

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_task(task: TaskModel) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "readable_id": task.readable_id,
        "project_id": str(task.project_id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "version": task.version,
        "claimed_by_machine_id": (
            str(task.claimed_by_machine_id) if task.claimed_by_machine_id else None
        ),
    }


async def studio_get_task(task_id: str, ctx: Context) -> dict[str, Any]:
    """Get one task by id (UUID string)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(task_id, "task_id")
        if isinstance(parsed, dict):
            return parsed
        task = await tasks_service.read_task(session, principal, parsed)
        if task is None:
            return {"error_code": "not_found", "message": f"task {task_id} not found"}
        return _compact_task(task)

    return await run_tool(ctx, _handler)


async def studio_get_active_tasks(project_id: str, ctx: Context) -> dict[str, Any]:
    """List active (created/in_progress/blocked) tasks for a project_id (UUID string)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(project_id, "project_id")
        if isinstance(parsed, dict):
            return parsed
        tasks = await projects_service.get_active_tasks(session, principal, parsed)
        return {"tasks": [_compact_task(t) for t in tasks]}

    return await run_tool(ctx, _handler)


async def studio_create_task(
    project_id: str,
    title: str,
    ctx: Context,
    description: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create a task on a project. `project_id` is a UUID string. Pass a
    caller-generated `idempotency_key` when this call might be retried
    (network timeout, transport error) — replaying the same key with the
    same arguments returns the original task instead of creating a second
    one; the same key with different arguments fails with
    `idempotency_key_payload_mismatch` (DEC-0027)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(project_id, "project_id")
        if isinstance(parsed, dict):
            return parsed
        # Ahead of `run_idempotent_dict`'s replay short-circuit — see
        # `routers/tasks.py::create_task` for why (DEC-0036).
        tasks_service.authorize_create(principal, parsed)

        async def _create() -> dict[str, Any]:
            task = await tasks_service.create_task(
                session,
                principal,
                TaskCreate(project_id=parsed, title=title, description=description),
            )
            return _compact_task(task)

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {"project_id": project_id, "title": title, "description": description},
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_create_task", request_hash, _create
        )

    return await run_tool(ctx, _handler)


async def studio_update_task(
    task_id: str,
    expected_version: int,
    ctx: Context,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Update a task's title/description/status. `expected_version` must match
    the task's current `version` (optimistic concurrency) — a mismatch returns
    `version_conflict` with the real server version, never a silent overwrite."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(task_id, "task_id")
        if isinstance(parsed, dict):
            return parsed
        task = await tasks_service.get_task(session, parsed)
        if task is None:
            return {"error_code": "not_found", "message": f"task {task_id} not found"}
        try:
            parsed_status = TaskStatus(status) if status is not None else None
        except ValueError:
            return {"error_code": "invalid_argument", "message": f"unknown status: {status!r}"}
        task_in = TaskUpdate(title=title, description=description, status=parsed_status)
        task = await tasks_service.update_task(session, principal, task, task_in, expected_version)
        return _compact_task(task)

    return await run_tool(ctx, _handler)


async def studio_claim_task(
    task_id: str, ctx: Context, agent_id: str | None = None
) -> dict[str, Any]:
    """Claim a task for the caller's machine (soft lock, sets status to
    in_progress). Fails with `already_claimed` if another machine holds it."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(task_id, "task_id")
        if isinstance(parsed, dict):
            return parsed
        parsed_agent_id: UUID | None = None
        if agent_id is not None:
            parsed_agent = parse_uuid(agent_id, "agent_id")
            if isinstance(parsed_agent, dict):
                return parsed_agent
            parsed_agent_id = parsed_agent
        task = await tasks_service.get_task(session, parsed)
        if task is None:
            return {"error_code": "not_found", "message": f"task {task_id} not found"}
        task = await tasks_service.claim_task(
            session, principal, task, principal.machine.id, parsed_agent_id
        )
        return _compact_task(task)

    return await run_tool(ctx, _handler)


async def studio_release_task(task_id: str, ctx: Context) -> dict[str, Any]:
    """Release a task's claim (clears claimed_by_machine_id/agent_id)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(task_id, "task_id")
        if isinstance(parsed, dict):
            return parsed
        task = await tasks_service.get_task(session, parsed)
        if task is None:
            return {"error_code": "not_found", "message": f"task {task_id} not found"}
        task = await tasks_service.release_task(session, principal, task)
        return _compact_task(task)

    return await run_tool(ctx, _handler)
