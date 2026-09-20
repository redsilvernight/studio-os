from __future__ import annotations

import logging

from fastapi import FastAPI

from studio_api.middleware import setup_middleware
from studio_api.observability import configure_logging
from studio_api.routers import (
    agents,
    ai_work,
    auth,
    builds,
    claims,
    decisions,
    events,
    github,
    health,
    heartbeats,
    library,
    machines,
    metrics,
    producer,
    projects,
    resolutions,
    review_queue,
    roadmaps,
    runtime_bindings,
    runtimes,
    sessions,
    tasks,
    timeline,
    transfers,
    users,
)

logger = logging.getLogger(__name__)

APP_DESCRIPTION = (
    "Shared coordination API for Studio OS projects: tasks, resource "
    "claims, work sessions, decisions, AI work logs, events, and file "
    "transfer metadata. Every operation under `/api/v1` requires machine "
    "authentication (`Authorization: Bearer <machine-token>`, provisioned "
    "out of band) except `GET /healthz`, `GET /metrics` and the human "
    "dashboard login `POST /auth/token`. File bytes never flow through "
    "this API — transfers exchange metadata and short-lived signed URLs "
    "only, uploads and downloads go directly to object storage. Replayable "
    "creations accept `Idempotency-Key`; concurrent updates use "
    "`If-Match-Version`; permission refusals answer `403 forbidden` and "
    "are final."
)

OPENAPI_TAG_DESCRIPTIONS: dict[str, str] = {
    "health": "Liveness, metrics and dashboard login probes (unauthenticated).",
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
    "library": (
        "Reusable AI definitions (rules, skills, agent definitions, model "
        "profiles, workflows) with immutable versions, explicit activation "
        "and project locks. User-scope rows are owner-or-admin only."
    ),
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
    "github": (
        "GitHub ingress and wiring. The webhook endpoint is signed "
        "(X-Hub-Signature-256), never Bearer-authenticated; integrations "
        "and builds are read by any authenticated machine, written by "
        "privileged roles or the server itself."
    ),
    "builds": (
        "CI builds observed on wired GitHub repositories. Server-written "
        "(webhook, reconcile worker); read-only over HTTP."
    ),
    "producer": (
        "Studio Producer: bounded, deterministic analyses over a project's "
        "shared state. Synchronous in v1; never mutates tasks or claims."
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
    "runtime-bindings": (
        "Stored runtime choices (P4) for logical library keys. The router "
        "never recomputes precedence — it stores, reads and releases "
        "choices; selection happens in the services and the resolution "
        "engine. Session overrides are ephemeral and never stored here."
    ),
    "runtimes": (
        "Declared runtimes (P6 registry, generic — never provider-specific). "
        "Register, read, update under optimistic concurrency, and logically "
        "revoke. No secret is ever accepted or stored."
    ),
    "resolutions": (
        "Canonical full resolution of an `AgentDefinition` to its "
        "`ResolvedAgentDefinition` (P5 engine via `resolve_full`): "
        "effective definition, rules, skills, model profile, winning "
        "runtime, compatibility verdict and structured provenance. Pure "
        "read — no fallback, no persistence."
    ),
    "roadmaps": (
        "Project roadmaps (Roadmap -> Phase -> Step): a plan, never work status — "
        "Tasks stay the units of work and step state/progress are derived from "
        "linked Tasks. Lifecycle draft/proposed/active/completed/archived through "
        "one transitions endpoint, atomic reordering, dependencies (DAG), "
        "Step<->Task links, idempotent Task hydration with preview, and import/"
        "export of the neutral `studio.roadmap/v1` document. No provider, model or "
        "harness concept and no server-side LLM."
    ),
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

    from studio_api.jwt_auth import is_weak_jwt_secret
    from studio_api.settings import get_settings

    settings = get_settings()
    configure_logging(settings.log_format, settings.log_level)
    setup_middleware(app, settings)

    if is_weak_jwt_secret(settings.jwt_secret):
        logger.warning(
            "STUDIO_JWT_SECRET is using a default or short value (< 32 bytes); "
            "set a strong secret in production"
        )

    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(projects.router)
    app.include_router(tasks.router)
    app.include_router(sessions.router)
    app.include_router(claims.router)
    app.include_router(decisions.router)
    app.include_router(library.router)
    app.include_router(library.locks_router)
    app.include_router(runtime_bindings.router)
    app.include_router(runtimes.router)
    app.include_router(resolutions.router)
    app.include_router(agents.router)
    app.include_router(ai_work.router)
    app.include_router(review_queue.router)
    app.include_router(timeline.router)
    app.include_router(github.router)
    app.include_router(builds.router)
    app.include_router(producer.router)
    app.include_router(heartbeats.router)
    app.include_router(events.router)
    app.include_router(transfers.router)
    app.include_router(machines.router)
    app.include_router(users.router)
    app.include_router(roadmaps.router)

    return app


app = create_app()
