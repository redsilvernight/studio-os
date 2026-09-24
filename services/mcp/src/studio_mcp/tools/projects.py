from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import projects as projects_service
from studio_api.services.authz import Principal

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


async def studio_get_projects(ctx: Context) -> dict[str, Any]:
    """List active (non-archived) Studio OS projects, compact fields only."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        projects = await projects_service.list_projects(session, principal)
        return {"projects": [{"id": str(p.id), "slug": p.slug, "name": p.name} for p in projects]}

    return await run_tool(ctx, _handler)


async def studio_get_project_state(project_id: str, ctx: Context) -> dict[str, Any]:
    """Get a project's active tasks and active resource claims — the bootstrap
    view a client/agent should read before starting work on it."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_id = parse_uuid(project_id, "project_id")
        if isinstance(parsed_id, dict):
            return parsed_id

        await projects_service.get_project(session, principal, parsed_id)
        tasks = await projects_service.get_active_tasks(session, principal, parsed_id)
        claims = await projects_service.get_active_claims(session, principal, parsed_id)
        return {
            "project_id": project_id,
            "active_tasks": [
                {"id": str(t.id), "title": t.title, "status": t.status} for t in tasks
            ],
            "active_claims": [
                {"id": str(c.id), "resource_path": c.resource_path, "status": c.status}
                for c in claims
            ],
        }

    return await run_tool(ctx, _handler)
