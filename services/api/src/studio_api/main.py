from __future__ import annotations

from fastapi import FastAPI

from studio_api.routers import (
    agents,
    ai_work,
    claims,
    decisions,
    events,
    health,
    heartbeats,
    machines,
    projects,
    sessions,
    tasks,
    transfers,
    users,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Studio OS API", version="1")

    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(tasks.router)
    app.include_router(sessions.router)
    app.include_router(claims.router)
    app.include_router(decisions.router)
    app.include_router(agents.router)
    app.include_router(ai_work.router)
    app.include_router(heartbeats.router)
    app.include_router(events.router)
    app.include_router(transfers.router)
    app.include_router(machines.router)
    app.include_router(users.router)

    return app


app = create_app()
