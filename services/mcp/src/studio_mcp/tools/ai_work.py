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

_MAX_AI_WORK_LIMIT = 200
_AI_WORK_FIELDS = frozenset(
    {
        "id",
        "project_id",
        "task_id",
        "agent_id",
        "session_id",
        "summary",
        "status",
        "changed_files",
        "tests_run",
        "started_at",
        "ended_at",
    }
)


def _compact_ai_work(work: AIWorkLogModel) -> dict[str, Any]:
    return {
        "id": str(work.id),
        "project_id": str(work.project_id),
        "task_id": str(work.task_id) if work.task_id else None,
        "agent_id": str(work.agent_id),
        "session_id": str(work.session_id) if work.session_id else None,
        "summary": work.summary,
        "status": work.status,
        "changed_files": work.changed_files,
        "tests_run": work.tests_run,
        "started_at": work.started_at.isoformat(),
        "ended_at": work.ended_at.isoformat() if work.ended_at else None,
    }


async def studio_get_ai_work(
    ctx: Context,
    project_id: str | None = None,
    task_id: str | None = None,
    limit: int = 20,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """List AI Work Ledger entries, most recent first, optionally filtered by
    project_id/task_id (UUID strings). `limit` (1..200, default 20) bounds the
    response; select response `fields` to keep it small (`id` is always
    included)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        if not 1 <= limit <= _MAX_AI_WORK_LIMIT:
            return {
                "error_code": "invalid_argument",
                "message": f"limit must be within 1..{_MAX_AI_WORK_LIMIT}",
            }
        selected_fields = _AI_WORK_FIELDS if fields is None else frozenset(fields) | {"id"}
        unknown_fields = selected_fields - _AI_WORK_FIELDS
        if unknown_fields:
            return {
                "error_code": "invalid_argument",
                "message": f"unknown fields: {', '.join(sorted(unknown_fields))}",
            }
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
            session, principal, project_id=parsed_project_id, task_id=parsed_task_id
        )
        ordered = sorted(entries, key=lambda work: (work.started_at, str(work.id)), reverse=True)
        selected = ordered[:limit]
        items = [
            {key: value for key, value in _compact_ai_work(work).items() if key in selected_fields}
            for work in selected
        ]
        return {
            "ai_work": items,
            "returned": len(items),
            "additional_available": len(ordered) - len(items),
        }

    return await run_tool(ctx, _handler)


async def studio_log_ai_work(
    project_id: str,
    summary: str,
    agent_id: str,
    ctx: Context,
    ai_work_id: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    changed_files: list[str] | None = None,
    tests_run: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Log AI work: creates a new entry when `ai_work_id` is omitted, or
    updates the existing entry when given — one tool for the whole lifecycle,
    per TECH/07_MCP_CONTRACT.md. On creation, `status` (default `started`),
    `changed_files` and `tests_run` are honored, so finished work is logged
    in one call; `approved`/`changes_requested` are refused. On update,
    `summary` replaces the stored one and only non-null fields change.
    `session_id` (L3) links the entry to the work session for handoff
    traceability. `idempotency_key` makes the call replay-safe (same key
    returns the original result)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        import json

        from studio_api.services import idempotency as idempotency_service

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
            parsed_session_id = None
            if session_id is not None:
                parsed_sess = parse_uuid(session_id, "session_id")
                if isinstance(parsed_sess, dict):
                    return parsed_sess
                parsed_session_id = parsed_sess
            work = await ai_work_service.update_ai_work(
                session,
                principal,
                existing,
                AIWorkLogUpdate(
                    summary=summary,
                    status=parsed_status,
                    changed_files=changed_files,
                    tests_run=tests_run,
                    session_id=parsed_session_id,
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
        parsed_session_id = None
        if session_id is not None:
            parsed_sess = parse_uuid(session_id, "session_id")
            if isinstance(parsed_sess, dict):
                return parsed_sess
            parsed_session_id = parsed_sess

        async def _create() -> dict[str, Any]:
            work = await ai_work_service.create_ai_work(
                session,
                principal,
                AIWorkLogCreate(
                    task_id=parsed_task_id,
                    project_id=parsed_project_id,
                    agent_id=parsed_agent_id,
                    machine_id=principal.machine.id,
                    session_id=parsed_session_id,
                    summary=summary,
                    status=parsed_status or AIWorkStatus.STARTED,
                    changed_files=changed_files or [],
                    tests_run=tests_run or [],
                ),
            )
            return _compact_ai_work(work)

        if idempotency_key is not None:
            request_hash = idempotency_service.hash_request(
                json.dumps(
                    {
                        "project_id": project_id,
                        "summary": summary,
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "session_id": session_id,
                        "status": status,
                        "changed_files": changed_files,
                        "tests_run": tests_run,
                    },
                    sort_keys=True,
                ).encode()
            )
            return await idempotency_service.run_idempotent_dict(
                session, idempotency_key, "MCP studio_log_ai_work", request_hash, _create
            )

        return await _create()

    return await run_tool(ctx, _handler)
