from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    description="Liveness probe of the console process itself (unauthenticated).",
)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/readyz",
    description=(
        "Readiness probe: the console serves aggregates only, so it reports "
        "ready as soon as it answers — a database outage surfaces as `503` on "
        "the aggregate routes, never as a fake figure."
    ),
)
async def readyz() -> dict[str, str]:
    return {"status": "ready"}
