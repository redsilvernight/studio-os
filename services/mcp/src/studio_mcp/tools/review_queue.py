from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import review_queue as review_queue_service
from studio_api.services.authz import Principal
from studio_contracts.review_queue import ReviewQueue

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_review_queue(queue: ReviewQueue) -> dict[str, Any]:
    return {
        "items": [item.model_dump(mode="json") for item in queue.items],
        "generated_at": queue.generated_at.isoformat(),
    }


async def studio_get_review_queue(
    ctx: Context,
    project_id: str | None = None,
    conflict_window_hours: int | None = None,
) -> dict[str, Any]:
    """Aggregated view of everything waiting on a human decision: AI work in
    review_requested, decisions still proposed (resolve via
    studio_accept_decision / studio_supersede_decision, admin-only), recent
    resource.conflict events (best-effort, time-windowed — no persisted
    conflict state exists), failed builds (informational), and opened PRs with
    no merge yet (best-effort, time-windowed). Also serves as the
    notifications surface: there is no separate notifications tool. Clients
    must tolerate an unknown kind."""

    async def _handler(session: AsyncSession, _principal: Principal) -> dict[str, Any]:
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        kwargs: dict[str, Any] = {"project_id": parsed_project_id}
        if conflict_window_hours is not None:
            kwargs["conflict_window_hours"] = conflict_window_hours
        queue = await review_queue_service.get_review_queue(session, **kwargs)
        return _compact_review_queue(queue)

    return await run_tool(ctx, _handler)
