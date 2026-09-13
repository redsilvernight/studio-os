from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.machine import MachineModel
from studio_api.services import decisions as decisions_service
from studio_contracts.decisions import DecisionCreate

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_decision(decision: DecisionModel) -> dict[str, Any]:
    return {
        "id": str(decision.id),
        "readable_id": decision.readable_id,
        "project_id": str(decision.project_id) if decision.project_id else None,
        "task_id": str(decision.task_id) if decision.task_id else None,
        "title": decision.title,
        "body": decision.body,
        "status": decision.status,
        "created_at": decision.created_at.isoformat(),
    }


async def studio_get_decisions(ctx: Context, project_id: str | None = None) -> dict[str, Any]:
    """List decisions, optionally filtered by project_id (UUID string)."""

    async def _handler(session: AsyncSession, _machine: MachineModel) -> dict[str, Any]:
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        decisions = await decisions_service.list_decisions(session, project_id=parsed_project_id)
        return {"decisions": [_compact_decision(d) for d in decisions]}

    return await run_tool(ctx, _handler)


async def studio_add_decision(
    title: str,
    body: str,
    ctx: Context,
    project_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Record a Decision (DEC-XXXX). `proposed_by` is derived from the caller's
    authenticated machine — the caller cannot claim another actor's identity."""

    async def _handler(session: AsyncSession, machine: MachineModel) -> dict[str, Any]:
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        parsed_task_id = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task_id = parsed
        decision = await decisions_service.create_decision(
            session,
            DecisionCreate(
                project_id=parsed_project_id,
                task_id=parsed_task_id,
                title=title,
                body=body,
                proposed_by_type="agent",
                proposed_by_id=machine.owner_user_id,
            ),
        )
        return _compact_decision(decision)

    return await run_tool(ctx, _handler)
