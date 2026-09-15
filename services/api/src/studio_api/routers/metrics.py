from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from studio_api.observability import metrics_response

router = APIRouter(tags=["metrics"])


@router.get(
    "/metrics",
    description="Prometheus metrics endpoint.",
    responses={200: {"description": "Prometheus exposition format"}},
    include_in_schema=False,
)
async def metrics() -> Any:
    return metrics_response()
