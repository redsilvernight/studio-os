from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.services import task_launches as launches_service
from studio_api.services.authz import Principal
from studio_contracts.task_launch import LAUNCH_POLL_MAX, TaskLaunchView

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _launch_response(launch: TaskLaunchModel | TaskLaunchView) -> dict[str, Any]:
    return {
        "id": str(launch.id),
        "project_id": str(launch.project_id),
        "task_id": str(launch.task_id),
        "machine_id": str(launch.machine_id),
        "requested_by_user_id": str(launch.requested_by_user_id),
        "harness_id": launch.harness_id,
        "agent_stable_key": launch.agent_stable_key,
        "status": launch.status,
        "reason_code": launch.reason_code,
        "session_id": str(launch.session_id) if launch.session_id else None,
        "version": launch.version,
        "expires_at": launch.expires_at.isoformat(),
        "finished_at": launch.finished_at.isoformat() if launch.finished_at else None,
    }


def _view_response(view: TaskLaunchView) -> dict[str, Any]:
    return {
        **_launch_response(view),
        "protocol": {
            "status": view.protocol.status.value,
            "session_id": str(view.protocol.session_id) if view.protocol.session_id else None,
            "task_status": view.protocol.task_status.value if view.protocol.task_status else None,
        },
    }


async def studio_get_task_launch(launch_id: str, ctx: Context) -> dict[str, Any]:
    """Get one task launch by id (UUID string) — read-only."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(launch_id, "launch_id")
        if isinstance(parsed, dict):
            return parsed
        launch = await launches_service.get_launch(session, principal, parsed)
        if launch is None:
            return {"error_code": "not_found", "message": f"task launch {launch_id} not found"}
        return _launch_response(launch)

    return await run_tool(ctx, _handler)


async def studio_list_task_launches(
    project_id: str,
    ctx: Context,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """List task launches of a project, oldest first — read-only. Each item
    carries its `protocol` proof (`not_applicable`, `awaiting`, `unverified`
    or `handed_off`) derived from the linked work session: `handed_off`
    means the agent followed the protocol and the session closed, never that
    the task is done."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(project_id, "project_id")
        if isinstance(parsed, dict):
            return parsed
        if limit is not None and not 1 <= limit <= 500:
            return {
                "error_code": "invalid_argument",
                "message": "limit must be within 1..500",
            }
        launches = await launches_service.list_launches(
            session, principal, parsed, limit=limit or 100, offset=offset
        )
        views = await launches_service.protocol_views(session, launches)
        return {"launches": [_view_response(view) for view in views]}

    return await run_tool(ctx, _handler)


async def studio_pull_pending_launches(ctx: Context) -> dict[str, Any]:
    """Pull the caller's own machine pending task launches (at most 20,
    oldest first) — read-only, changes nothing. The daemon calls this to
    learn which launches target it."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        pull = await launches_service.pull_pending(session, principal, principal.machine.id)
        items = [
            {
                "id": str(item.id),
                "project_id": str(item.project_id),
                "task_id": str(item.task_id),
                "harness_id": str(item.harness_id),
                "agent_stable_key": item.agent_stable_key,
                "status": item.status.value,
                "version": item.version,
                "expires_at": item.expires_at.isoformat(),
            }
            for item in pull.items
        ]
        return {"launches": items, "max_items": LAUNCH_POLL_MAX}

    return await run_tool(ctx, _handler)
