from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    description=(
        "Liveness probe. Needs no credential and carries no security "
        "requirement — one of the unauthenticated operations, alongside "
        "`GET /version`, `GET /metrics` and the human dashboard login `POST /auth/token`. "
        'Answers `{"status": "ok"}` when the service is up; use it before '
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
