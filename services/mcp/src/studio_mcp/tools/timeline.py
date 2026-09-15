from __future__ import annotations

from datetime import datetime
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import timeline as timeline_service
from studio_api.services.authz import Principal
from studio_contracts.timeline import Timeline

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_timeline(timeline: Timeline) -> dict[str, Any]:
    return {
        "project_id": str(timeline.project_id),
        "days": [
            {
                "date": day.date.isoformat(),
                "events": [event.model_dump(mode="json") for event in day.events],
            }
            for day in timeline.days
        ],
    }


async def studio_get_timeline(
    project_id: str,
    ctx: Context,
    since: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Day-grouped project activity (newest day first), unfiltered — the full
    history, not an actionable signal (see studio_get_review_queue for
    that). `since` is an ISO-8601 timestamp."""

    async def _handler(session: AsyncSession, _principal: Principal) -> dict[str, Any]:
        parsed_project_id = parse_uuid(project_id, "project_id")
        if isinstance(parsed_project_id, dict):
            return parsed_project_id
        parsed_since = None
        if since is not None:
            try:
                parsed_since = datetime.fromisoformat(since)
            except ValueError:
                return {
                    "error_code": "invalid_argument",
                    "message": f"since is not an ISO-8601 timestamp: {since!r}",
                }
        kwargs: dict[str, Any] = {"since": parsed_since}
        if limit is not None:
            kwargs["limit"] = limit
        timeline = await timeline_service.get_timeline(session, parsed_project_id, **kwargs)
        return _compact_timeline(timeline)

    return await run_tool(ctx, _handler)
