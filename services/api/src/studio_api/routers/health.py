from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    description=(
        "Liveness probe. Needs no credential and carries no security "
        "requirement — the only unauthenticated operation. Answers "
        '`{"status": "ok"}` when the service is up; use it before '
        "authenticating anything else."
    ),
    responses={
        200: {
            "description": "The service is up.",
            "content": {"application/json": {"example": {"status": "ok"}}},
        }
    },
)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
