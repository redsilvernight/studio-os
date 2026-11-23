"""Operator console application: a separate deployment (own origin, own
token, own static front) over the shared cluster.

It is not mounted by the core API. Run it with `studio-operator` (or
`uvicorn studio_operator.main:app`) behind its own hostname.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from studio_operator.routers import billing, dashboard, health, session, studios, usage
from studio_operator.settings import get_settings, is_weak_jwt_secret

STATIC_DIR = Path(__file__).resolve().parent / "static"

APP_DESCRIPTION = (
    "Studio OS operator console: a separate application (own origin, token and "
    "deployment) for instance operators. Login requires a configured operator "
    "with a TOTP secret. Every view is an aggregate — service health, phase-M "
    "measures, studios, usage, billing state, suspensions — and no route reads "
    "client content: no project, file, note or message is ever exposed."
)


def create_app() -> FastAPI:
    settings = get_settings()
    if is_weak_jwt_secret(settings.jwt_secret) and settings.environment == "production":
        raise RuntimeError(
            "STUDIO_OPERATOR_JWT_SECRET is using a default or short value (< 32 bytes); "
            "refusing to start in production (set a strong secret, or "
            "STUDIO_OPERATOR_ENVIRONMENT=dev for local development)"
        )

    app = FastAPI(
        title="Studio OS operator console",
        version="1",
        description=APP_DESCRIPTION,
        openapi_tags=[
            {"name": "session", "description": "Operator login (MFA) and identity."},
            {"name": "dashboard", "description": "Service health and phase-M measures."},
            {"name": "studios", "description": "Studio directory, detail and suspension."},
            {"name": "usage", "description": "Aggregate usage per studio and globally."},
            {
                "name": "suspensions",
                "description": "Suspended studios, billing and break-glass availability.",
            },
            {"name": "health", "description": "Liveness and readiness probes."},
        ],
    )

    app.include_router(health.router)
    app.include_router(session.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(studios.router, prefix="/api/v1")
    app.include_router(usage.router, prefix="/api/v1")
    app.include_router(billing.router, prefix="/api/v1")

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="console")

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "studio_operator.main:app",
        host="127.0.0.1",
        port=8090,
        log_level="info",
    )
