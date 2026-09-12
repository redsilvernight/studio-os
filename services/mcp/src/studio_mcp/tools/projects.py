from __future__ import annotations

from typing import Any
from uuid import UUID

from studio_api.db.session import get_session_factory
from studio_api.services import projects as projects_service


async def studio_get_projects() -> list[dict[str, Any]]:
    """List active (non-archived) Studio OS projects, compact fields only."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        projects = await projects_service.list_projects(session)
        return [{"id": str(p.id), "slug": p.slug, "name": p.name} for p in projects]


async def studio_get_project_state(project_id: str) -> dict[str, Any]:
    """Get a project's active tasks and active resource claims — the bootstrap
    view a client/agent should read before starting work on it."""
    try:
        parsed_id = UUID(project_id)
    except ValueError:
        return {"error_code": "invalid_project_id", "message": f"not a UUID: {project_id!r}"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        project = await projects_service.get_project(session, parsed_id)
        if project is None:
            return {"error_code": "not_found", "message": f"project {project_id} not found"}

        tasks = await projects_service.get_active_tasks(session, parsed_id)
        claims = await projects_service.get_active_claims(session, parsed_id)
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
