from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.services import heartbeats as heartbeats_service
from studio_api.services import projects as projects_service
from studio_api.services.authz import Principal
from studio_api.settings import get_settings

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


async def studio_get_teammate_activity(project_id: str, ctx: Context) -> dict[str, Any]:
    """List the machines currently active on a project — derived from its
    active tasks and resource claims (machines aren't project-scoped
    themselves), each with a heartbeat-derived status
    (TECH/04_AUTH_SYNC_CONTRACT.md)."""

    async def _handler(session: AsyncSession, _principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(project_id, "project_id")
        if isinstance(parsed, dict):
            return parsed

        tasks = await projects_service.get_active_tasks(session, parsed)
        claims = await projects_service.get_active_claims(session, parsed)
        machine_ids = {t.claimed_by_machine_id for t in tasks if t.claimed_by_machine_id}
        machine_ids.update(c.claimed_by_machine_id for c in claims)

        settings = get_settings()
        teammates = []
        for machine_id in machine_ids:
            teammate = await session.get(MachineModel, machine_id)
            if teammate is None:
                continue
            owner = await session.get(UserModel, teammate.owner_user_id)
            teammates.append(
                {
                    "machine_id": str(teammate.id),
                    "display_name": teammate.display_name,
                    "owner_display_name": owner.display_name if owner else None,
                    "status": heartbeats_service.derive_status(teammate, settings).value,
                    "last_seen_at": (
                        teammate.last_seen_at.isoformat() if teammate.last_seen_at else None
                    ),
                }
            )
        return {"teammates": teammates}

    return await run_tool(ctx, _handler)
