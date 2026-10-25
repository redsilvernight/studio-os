from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services.authz import Principal
from studio_api.services.discovery import discover_product
from studio_api.settings import get_settings
from studio_contracts.discovery import DiscoveryIntent

from studio_mcp.errors import run_tool


async def studio_discover_capabilities(
    ctx: Context,
    intent: DiscoveryIntent = "overview",
    key: str | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Explain product capabilities, project startup and missing setup; detail by key."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        result = await discover_product(
            session,
            principal,
            get_settings(),
            intent=intent,
            key=key,
            limit=limit,
        )
        return result.model_dump(mode="json", exclude_none=True)

    return await run_tool(ctx, _handler)
