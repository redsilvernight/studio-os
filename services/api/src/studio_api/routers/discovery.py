from __future__ import annotations

from fastapi import APIRouter, Query
from studio_contracts.discovery import DiscoveryIntent, ProductDiscovery

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.services.discovery import discover_product
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["discovery"])


@router.get("/capabilities", response_model=ProductDiscovery)
async def capabilities(
    session: DbSession,
    principal: CurrentPrincipal,
    intent: DiscoveryIntent = "overview",
    key: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=6, ge=1, le=24),
) -> ProductDiscovery:
    return await discover_product(
        session, principal, get_settings(), intent=intent, key=key, limit=limit
    )
