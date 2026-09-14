from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.services import ai_work as ai_work_service
from studio_api.services.authz import Principal
from studio_contracts.ai_work import AIWorkLogCreate, AIWorkLogUpdate, AIWorkStatus

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_ai_work(work: AIWorkLogModel) -> dict[str, Any]:
    return {
        "id": str(work.id),
        "project_id": str(work.project_id),
        "task_id": str(work.task_id) if work.task_id else None,
        "agent_id": str(work.agent_id),
        "summary": work.summary,
        "status": work.status,
        "changed_files": work.changed_files,
        "tests_run": work.tests_run,
        "started_at": work.started_at.isoformat(),
        "ended_at": work.ended_at.isoformat() if work.ended_at else None,
    }


async def studio_get_ai_work(
    ctx: Context, project_id: str | None = None, task_id: str | None = None
) -> dict[str, Any]:
    """List AI Work Ledger entries, optionally filtered by project_id/task_id
    (UUID strings)."""

    async def _handler(session: AsyncSession, _principal: Principal) -> dict[str, Any]:
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
        entries = await ai_work_service.list_ai_work(
            session, project_id=parsed_project_id, task_id=parsed_task_id
        )
        return {"ai_work": [_compact_ai_work(w) for w in entries]}

    return await run_tool(ctx, _handler)


async def studio_log_ai_work(
    project_id: str,
    summary: str,
    agent_id: str,
    ctx: Context,
    ai_work_id: str | None = None,
    task_id: str | None = None,
    status: str | None = None,
    changed_files: list[str] | None = None,
    tests_run: list[str] | None = None,
) -> dict[str, Any]:
    """Log AI work: creates a new entry when `ai_work_id` is omitted (start of
    work), or updates the existing entry when given (e.g. to mark it
    `completed`/`failed` with changed_files/tests_run) — one tool for the
    whole lifecycle, per TECH/07_MCP_CONTRACT.md."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_agent_id = parse_uuid(agent_id, "agent_id")
        if isinstance(parsed_agent_id, dict):
            return parsed_agent_id
        try:
            parsed_status = AIWorkStatus(status) if status is not None else None
        except ValueError:
            return {"error_code": "invalid_argument", "message": f"unknown status: {status!r}"}

        if ai_work_id is not None:
            parsed_id = parse_uuid(ai_work_id, "ai_work_id")
            if isinstance(parsed_id, dict):
                return parsed_id
            existing = await session.get(AIWorkLogModel, parsed_id)
            if existing is None:
                return {"error_code": "not_found", "message": f"ai_work {ai_work_id} not found"}
            work = await ai_work_service.update_ai_work(
                session,
                principal,
                existing,
                AIWorkLogUpdate(
                    summary=summary,
                    status=parsed_status,
                    changed_files=changed_files,
                    tests_run=tests_run,
                ),
            )
            return _compact_ai_work(work)

        parsed_project_id = parse_uuid(project_id, "project_id")
        if isinstance(parsed_project_id, dict):
            return parsed_project_id
        parsed_task_id = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task_id = parsed
        work = await ai_work_service.create_ai_work(
            session,
            principal,
            AIWorkLogCreate(
                task_id=parsed_task_id,
                project_id=parsed_project_id,
                agent_id=parsed_agent_id,
                machine_id=principal.machine.id,
                summary=summary,
            ),
        )
        return _compact_ai_work(work)

    return await run_tool(ctx, _handler)
