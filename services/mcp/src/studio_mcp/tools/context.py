from __future__ import annotations

from mcp.server.mcpserver import Context
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import project_context as context_service
from studio_api.services.authz import Principal
from studio_api.services.project_context import PreparedContext

from studio_mcp.errors import McpError, run_tool
from studio_mcp.util import parse_uuid


async def studio_prepare_context(
    project_id: str,
    objective: str,
    ctx: Context,
    task_id: str | None = None,
    files: list[str] | None = None,
    limit: int = context_service.DEFAULT_LIMIT,
    max_chars: int = context_service.DEFAULT_MAX_CHARS,
) -> PreparedContext | McpError:
    """Prepare a compact, bounded project context for the stated objective:
    the task, related tasks, decisions, rules, skills and claims that matter,
    and — when the project has an active roadmap — its current step, blockers,
    linked tasks and acceptance criteria (never the whole roadmap)."""

    async def _handler(session: AsyncSession, principal: Principal) -> PreparedContext | McpError:
        parsed_project = parse_uuid(project_id, "project_id")
        if isinstance(parsed_project, dict):
            return McpError.model_validate(parsed_project)
        parsed_task = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return McpError.model_validate(parsed)
            parsed_task = parsed
        return await context_service.prepare_project_context(
            session,
            principal,
            parsed_project,
            objective,
            task_id=parsed_task,
            files=files,
            limit=limit,
            max_chars=max_chars,
        )

    raw = await run_tool(ctx, _handler)
    if isinstance(raw, dict):  # auth / HTTPException / IntegrityError envelopes
        try:
            return McpError.model_validate(raw)
        except ValidationError:
            return McpError(error_code="error", message=str(raw))
    return raw
