from __future__ import annotations

from uuid import UUID

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
    ctx: Context,
    objective: str | None = None,
    task_id: str | None = None,
    files: list[str] | None = None,
    limit: int = context_service.DEFAULT_LIMIT,
    max_chars: int = context_service.DEFAULT_MAX_CHARS,
    agent_stable_key: str | None = None,
    known_ids: dict[str, str] | None = None,
) -> PreparedContext | McpError:
    """Prepare a compact, bounded project context for the stated objective:
    the task, related tasks, decisions, rules, skills, recent AI work and
    claims that matter, and — when the project has an active roadmap — its
    current step, blockers, linked tasks and acceptance criteria (never the
    whole roadmap). When `task_id` is supplied, `objective` may be omitted and
    is derived from that task. Pass `known_ids` as `{id: content_hash}` to
    receive hash-matching items as `unchanged=true` references without their
    long text. Pass `agent_stable_key`
    so the agent's resolved rules/skills sort first (flagged `agent_applies`,
    still budgeted)."""

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
        parsed_known: dict[UUID, str] = {}
        if known_ids is not None:
            if len(known_ids) > context_service.MAX_KNOWN_IDS:
                return McpError(
                    error_code="invalid_argument",
                    message=(f"known_ids accepts at most {context_service.MAX_KNOWN_IDS} ids"),
                )
            for raw_id, content_hash in known_ids.items():
                parsed = parse_uuid(raw_id, "known_ids")
                if isinstance(parsed, dict):
                    return McpError.model_validate(parsed)
                if len(content_hash) != 64 or any(
                    c not in "0123456789abcdef" for c in content_hash
                ):
                    return McpError(
                        error_code="invalid_argument",
                        message="known_ids values must be lowercase SHA-256 hashes",
                    )
                parsed_known[parsed] = content_hash
        return await context_service.prepare_project_context(
            session,
            principal,
            parsed_project,
            objective,
            task_id=parsed_task,
            files=files,
            limit=limit,
            max_chars=max_chars,
            agent_stable_key=agent_stable_key,
            known_ids=parsed_known,
        )

    raw = await run_tool(ctx, _handler)
    if isinstance(raw, dict):  # auth / HTTPException / IntegrityError envelopes
        try:
            return McpError.model_validate(raw)
        except ValidationError:
            return McpError(error_code="error", message=str(raw))
    return raw
