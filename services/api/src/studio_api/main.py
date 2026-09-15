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
    review_queue,
    sessions,
    tasks,
    timeline,
    transfers,
    users,
)

APP_DESCRIPTION = (
    "Shared coordination API for Studio OS projects: tasks, resource "
    "claims, work sessions, decisions, AI work logs, events, and file "
    "transfer metadata. Every operation under `/api/v1` requires machine "
    "authentication (`Authorization: Bearer <machine-token>`, provisioned "
    "out of band) except `GET /healthz`. File bytes never flow through "
    "this API — transfers exchange metadata and short-lived signed URLs "
    "only, uploads and downloads go directly to object storage. Replayable "
    "creations accept `Idempotency-Key`; concurrent updates use "
    "`If-Match-Version`; permission refusals answer `403 forbidden` and "
    "are final."
)

OPENAPI_TAG_DESCRIPTIONS: dict[str, str] = {
    "health": "Unauthenticated liveness probe. The only operation that needs no credential.",
    "projects": (
        "Project registry. Creating a project requires a privileged role; "
        "reading is open to any authenticated machine."
    ),
    "tasks": "Work items with optimistic-concurrency updates and machine claims.",
    "sessions": "Work sessions tying a machine to a task over a time span.",
    "claims": (
        "Soft locks on resource paths (files, folders). A claim warns "
        "other machines through a conflict event — it never blocks a "
        "write, a Git operation, or a transfer."
    ),
    "decisions": "Recorded project decisions with stable human-readable ids.",
    "agents": (
        "Provenance identities attached to the caller's own authenticated "
        "machine. Registering an agent grants no permission and requires "
        "no prior knowledge: any writer may materialize its own identity "
        "here. Needed only to attribute AI work logs."
    ),
    "ai-work": (
        "AI work ledger. Entries reference an agent attached to the "
        "caller's own machine; foreign or unknown agents are rejected. "
        "Review transitions to approved/rejected require a privileged role."
    ),
    "review-queue": (
        "Aggregated view of AI work reviews, proposed decisions, and recent "
        "resource conflicts awaiting a human decision. Read-only; also "
        "serves as the notifications surface."
    ),
    "timeline": (
        "Day-grouped project activity derived from the event stream. "
        "Read-only, unfiltered history — see review-queue for what needs "
        "action."
    ),
    "heartbeats": (
        "Machine presence. Any authenticated machine — including read-only "
        "ones — may heartbeat; status is derived server-side."
    ),
    "events": (
        "Project activity feed. Every event carries a stable "
        "client-generated `event_id` (replay the same id, get the stored "
        "event, never a duplicate). Read history with `GET /events?since=` "
        "or subscribe live with `GET /events/stream` (Server-Sent Events, "
        "resumable). Identity fields are validated against the "
        "authenticated machine."
    ),
    "transfers": (
        "File transfer coordination: metadata and short-lived signed URLs "
        "only, never file bytes. The client uploads and downloads "
        "directly to object storage with the returned URLs."
    ),
    "machines": (
        "Machine provisioning (privileged role). The very first machine is created out of band."
    ),
    "users": "User provisioning (privileged role). The very first user is created out of band.",
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="Studio OS API",
        version="1",
        description=APP_DESCRIPTION,
        openapi_tags=[
            {"name": name, "description": description}
            for name, description in OPENAPI_TAG_DESCRIPTIONS.items()
        ],
    )

    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(tasks.router)
    app.include_router(sessions.router)
    app.include_router(claims.router)
    app.include_router(decisions.router)
    app.include_router(agents.router)
    app.include_router(ai_work.router)
    app.include_router(review_queue.router)
    app.include_router(timeline.router)
    app.include_router(heartbeats.router)
    app.include_router(events.router)
    app.include_router(transfers.router)
    app.include_router(machines.router)
    app.include_router(users.router)

    return app


app = create_app()
