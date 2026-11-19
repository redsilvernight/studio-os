from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.task import TaskModel
from studio_api.services import idempotency as idempotency_service
from studio_api.services import projects as projects_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal, ensure_optional_project_in_studio
from studio_contracts.tasks import TaskCreate, TaskStatus, TaskUpdate

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid

_ACTIVE_TASK_FIELDS = frozenset(
    {
        "id",
        "readable_id",
        "project_id",
        "title",
        "description",
        "status",
        "version",
        "claimed_by_machine_id",
    }
)
_MAX_ACTIVE_TASK_LIMIT = 100


def _task_response(task: TaskModel, *, verbose: bool) -> dict[str, Any]:
    if not verbose:
        return {
            "id": str(task.id),
            "status": task.status,
            "version": task.version,
            "claimed_by_machine_id": (
                str(task.claimed_by_machine_id) if task.claimed_by_machine_id else None
            ),
        }
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
        return _task_response(task, verbose=True)

    return await run_tool(ctx, _handler)


async def studio_get_active_tasks(
    project_id: str,
    ctx: Context,
    title_prefix: str | None = None,
    limit: int | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """List active tasks for a project, bounded to 100 by default.
    Set `limit` (1..100) for a smaller deterministic response. Optionally
    filter by case-insensitive `title_prefix` and select response `fields`;
    `id` is always included."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(project_id, "project_id")
        if isinstance(parsed, dict):
            return parsed
        if limit is not None and not 1 <= limit <= _MAX_ACTIVE_TASK_LIMIT:
            return {
                "error_code": "invalid_argument",
                "message": f"limit must be within 1..{_MAX_ACTIVE_TASK_LIMIT}",
            }
        prefix = title_prefix.strip().casefold() if title_prefix is not None else None
        if title_prefix is not None and not prefix:
            return {
                "error_code": "invalid_argument",
                "message": "title_prefix must not be empty",
            }
        selected_fields = _ACTIVE_TASK_FIELDS if fields is None else frozenset(fields) | {"id"}
        unknown_fields = selected_fields - _ACTIVE_TASK_FIELDS
        if unknown_fields:
            return {
                "error_code": "invalid_argument",
                "message": f"unknown fields: {', '.join(sorted(unknown_fields))}",
            }
        tasks = await projects_service.get_active_tasks(session, principal, parsed)
        ordered = sorted(tasks, key=lambda task: (task.title.casefold(), str(task.id)))
        if prefix is not None:
            ordered = [task for task in ordered if task.title.casefold().startswith(prefix)]
        total = len(ordered)
        selected = ordered[: 100 if limit is None else limit]
        items = [
            {
                key: value
                for key, value in _task_response(task, verbose=True).items()
                if key in selected_fields
            }
            for task in selected
        ]
        return {
            "tasks": items,
            "returned": len(items),
            "additional_available": total - len(items),
        }

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
        await ensure_optional_project_in_studio(session, principal, parsed, "write")

        async def _create() -> dict[str, Any]:
            task = await tasks_service.create_task(
                session,
                principal,
                TaskCreate(project_id=parsed, title=title, description=description),
            )
            return _task_response(task, verbose=True)

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {"project_id": project_id, "title": title, "description": description},
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session,
            idempotency_key,
            "MCP studio_create_task",
            request_hash,
            _create,
            studio_id=principal.studio_id,
        )

    return await run_tool(ctx, _handler)


async def studio_update_task(
    task_id: str,
    expected_version: int,
    ctx: Context,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Update a task's title/description/status. `expected_version` must match
    the task's current `version` (optimistic concurrency) — a mismatch returns
    `version_conflict` with the real server version, never a silent overwrite.
    `status="abandoned"` closes the task without delivery (refused from
    `completed` with `invalid_transition`) and clears its claim.
    Pass `verbose=false` for the compact workflow response."""

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
        return _task_response(task, verbose=verbose)

    return await run_tool(ctx, _handler)
