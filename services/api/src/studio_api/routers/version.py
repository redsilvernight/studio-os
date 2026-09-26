from __future__ import annotations

from fastapi import APIRouter
from studio_contracts.version import CLIENT_FAMILIES, VersionInfo

from studio_api.compat import SERVER_VERSION, family_latest, family_minimum
from studio_api.settings import get_settings

router = APIRouter(tags=["version"])


@router.get(
    "/version",
    response_model=VersionInfo,
    description=(
        "Compatibility probe. Needs no credential — one of the unauthenticated "
        "operations, alongside `GET /healthz` and `GET /metrics`. Reports the "
        "API contract version, the running server build, and per client family "
        "the oldest build still served (`minimum_supported`) with the newest "
        "known build (`latest`). Old clients ignore it safely."
    ),
    responses={
        200: {
            "description": "Version negotiation snapshot.",
            "content": {
                "application/json": {
                    "example": {
                        "api_version": "1",
                        "server_version": "0.1.0",
                        "minimum_supported": {
                            "desktop": "0.1.0",
                            "daemon": "0.1.0",
                            "dashboard": "0.1.0",
                        },
                        "latest": {
                            "desktop": "0.1.0",
                            "daemon": "0.1.0",
                            "dashboard": "0.1.0",
                        },
                    }
                }
            },
        }
    },
)
async def version() -> VersionInfo:
    settings = get_settings()
    return VersionInfo(
        api_version=settings.api_version,
        server_version=SERVER_VERSION,
        minimum_supported={
            family: str(family_minimum(settings, family)) for family in CLIENT_FAMILIES
        },
        latest={family: str(family_latest(settings, family)) for family in CLIENT_FAMILIES},
    )
