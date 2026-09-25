"""Fail-closed access registry of every HTTP operation (DEC-0100 §12).

Every mounted route — including the ones hidden from the OpenAPI document —
must be classified here. `tests/api/test_access_registry.py` fails when a
route is missing or an entry is stale, and generates the outsider matrix
(an active User without membership) from the `project` entries.

The registry documents intent and drives tests; it never grants anything at
runtime — authorization stays in the services (`studio_api.services.authz`).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Literal

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Route

AccessClass = Literal["project", "instance", "own", "public"]
"""
- `project`: reads or writes data that belongs (or may belong) to a project.
  A non-member gets `403 forbidden` (identical to a nonexistent project) or a
  collection filtered to the projects they can access.
- `instance`: instance-wide provisioning guarded by role, never tied to an
  existing project's data.
- `own`: the caller's own identity or user-private resources (self/admin).
- `public`: no machine authentication (probes, login, signed webhook, docs).
"""

Operation = tuple[str, str]
"""`(METHOD, path template)` as mounted, e.g. `("GET", "/api/v1/tasks/{task_id}")`."""

_P: AccessClass = "project"

HTTP_ACCESS: Mapping[Operation, AccessClass] = {
    # Public: unauthenticated probes, login, signed webhook, API docs.
    ("GET", "/healthz"): "public",
    ("GET", "/metrics"): "public",
    ("POST", "/api/v1/auth/token"): "public",
    ("POST", "/api/v1/github/webhook"): "public",
    ("GET", "/openapi.json"): "public",
    ("GET", "/docs"): "public",
    ("GET", "/docs/oauth2-redirect"): "public",
    ("GET", "/redoc"): "public",
    # Instance: role-guarded provisioning, no existing project's data.
    ("POST", "/api/v1/projects"): "instance",
    ("GET", "/api/v1/users"): "instance",
    ("POST", "/api/v1/users"): "instance",
    ("POST", "/api/v1/machines"): "instance",
    ("POST", "/api/v1/machines/{machine_id}/revoke"): "instance",
    # Own: the caller's machine, agents and user-private runtimes.
    ("GET", "/api/v1/machines"): "own",
    ("GET", "/api/v1/machines/me"): "own",
    ("GET", "/api/v1/agents"): "own",
    ("POST", "/api/v1/agents"): "own",
    ("POST", "/api/v1/heartbeats"): "own",
    ("GET", "/api/v1/runtimes"): "own",
    ("POST", "/api/v1/runtimes"): "own",
    ("GET", "/api/v1/runtimes/{runtime_id}"): "own",
    ("PATCH", "/api/v1/runtimes/{runtime_id}"): "own",
    ("POST", "/api/v1/runtimes/{runtime_id}/revoke"): "own",
    # Project.
    ("GET", "/api/v1/projects"): _P,
    ("GET", "/api/v1/projects/{project_id}"): _P,
    ("GET", "/api/v1/projects/{project_id}/state"): _P,
    ("GET", "/api/v1/projects/{project_id}/members"): _P,
    ("PUT", "/api/v1/projects/{project_id}/members/{user_id}"): _P,
    ("DELETE", "/api/v1/projects/{project_id}/members/{user_id}"): _P,
    ("POST", "/api/v1/projects/initialization/preview"): _P,
    ("POST", "/api/v1/projects/initialization/apply"): _P,
    ("GET", "/api/v1/tasks"): _P,
    ("POST", "/api/v1/tasks"): _P,
    ("GET", "/api/v1/tasks/{task_id}"): _P,
    ("PATCH", "/api/v1/tasks/{task_id}"): _P,
    ("POST", "/api/v1/tasks/{task_id}/claim"): _P,
    ("POST", "/api/v1/tasks/{task_id}/release"): _P,
    ("GET", "/api/v1/sessions"): _P,
    ("POST", "/api/v1/sessions"): _P,
    ("PATCH", "/api/v1/sessions/{session_id}/end"): _P,
    ("GET", "/api/v1/claims"): _P,
    ("POST", "/api/v1/claims"): _P,
    ("POST", "/api/v1/claims/{claim_id}/renew"): _P,
    ("DELETE", "/api/v1/claims/{claim_id}"): _P,
    ("GET", "/api/v1/decisions"): _P,
    ("POST", "/api/v1/decisions"): _P,
    ("POST", "/api/v1/decisions/{decision_id}/accept"): _P,
    ("POST", "/api/v1/decisions/{decision_id}/supersede"): _P,
    ("GET", "/api/v1/library"): _P,
    ("POST", "/api/v1/library"): _P,
    ("GET", "/api/v1/library/{resource_id}"): _P,
    ("GET", "/api/v1/library/{resource_id}/versions"): _P,
    ("POST", "/api/v1/library/{resource_id}/versions"): _P,
    ("POST", "/api/v1/library/{resource_id}/activate"): _P,
    ("POST", "/api/v1/library/{resource_id}/deprecate"): _P,
    ("GET", "/api/v1/library-locks"): _P,
    ("POST", "/api/v1/library-locks"): _P,
    ("DELETE", "/api/v1/library-locks/{lock_id}"): _P,
    ("GET", "/api/v1/runtime-bindings"): _P,
    ("POST", "/api/v1/runtime-bindings"): _P,
    ("GET", "/api/v1/runtime-bindings/{binding_id}"): _P,
    ("DELETE", "/api/v1/runtime-bindings/{binding_id}"): _P,
    ("POST", "/api/v1/resolutions"): _P,
    ("GET", "/api/v1/ai-work"): _P,
    ("POST", "/api/v1/ai-work"): _P,
    ("PATCH", "/api/v1/ai-work/{work_id}"): _P,
    ("GET", "/api/v1/review-queue"): _P,
    ("GET", "/api/v1/timeline"): _P,
    ("POST", "/api/v1/projects/{project_id}/github-integration"): _P,
    ("GET", "/api/v1/projects/{project_id}/github-integration"): _P,
    ("PATCH", "/api/v1/projects/{project_id}/github-integration"): _P,
    ("GET", "/api/v1/builds"): _P,
    ("GET", "/api/v1/builds/{build_id}"): _P,
    ("POST", "/api/v1/producer-jobs"): _P,
    ("GET", "/api/v1/producer-jobs"): _P,
    ("GET", "/api/v1/producer-jobs/{job_id}"): _P,
    ("POST", "/api/v1/events"): _P,
    ("GET", "/api/v1/events"): _P,
    ("GET", "/api/v1/events/stream"): _P,
    ("GET", "/api/v1/transfers"): _P,
    ("POST", "/api/v1/transfers"): _P,
    ("GET", "/api/v1/transfers/consumption"): _P,
    ("GET", "/api/v1/transfers/{transfer_id}"): _P,
    ("DELETE", "/api/v1/transfers/{transfer_id}"): _P,
    ("POST", "/api/v1/transfers/{transfer_id}/upload/initiate"): _P,
    ("POST", "/api/v1/transfers/{transfer_id}/upload/refresh-parts"): _P,
    ("POST", "/api/v1/transfers/{transfer_id}/upload/complete"): _P,
    ("POST", "/api/v1/transfers/{transfer_id}/download-url"): _P,
    ("GET", "/api/v1/projects/{project_id}/roadmaps"): _P,
    ("POST", "/api/v1/roadmaps"): _P,
    ("POST", "/api/v1/roadmaps/import"): _P,
    ("GET", "/api/v1/roadmaps/{roadmap_id}"): _P,
    ("PATCH", "/api/v1/roadmaps/{roadmap_id}"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/transitions"): _P,
    ("GET", "/api/v1/roadmaps/{roadmap_id}/export"): _P,
    ("GET", "/api/v1/roadmaps/{roadmap_id}/revisions"): _P,
    ("GET", "/api/v1/roadmaps/{roadmap_id}/revisions/{revision_no}"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/proposals"): _P,
    ("GET", "/api/v1/roadmaps/{roadmap_id}/proposals/{revision_no}/diff"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/proposals/{revision_no}/review"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/phases"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/phases/reorder"): _P,
    ("PATCH", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}"): _P,
    ("DELETE", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}/steps/reorder"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}/steps"): _P,
    ("PATCH", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}"): _P,
    ("DELETE", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}"): _P,
    ("PATCH", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/progress"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/dependencies"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/dependencies/remove"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/links"): _P,
    ("DELETE", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/links/{task_id}"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/hydration/preview"): _P,
    ("POST", "/api/v1/roadmaps/{roadmap_id}/hydration/apply"): _P,
}


def iter_operations(app: FastAPI) -> Iterator[Operation]:
    """Yield every mounted `(METHOD, path)`, hidden routes included.

    Fail-closed: an unknown route type raises instead of being skipped, so a
    new mounting mechanism cannot silently escape the registry."""
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:  # FastAPI >= 0.140: lazily included routers
            for context in contexts():
                yield from _methods(context.path, context.methods)
        elif isinstance(route, APIRoute | Route):
            yield from _methods(route.path, route.methods)
        else:
            raise TypeError(f"unclassifiable route type: {type(route).__name__}")


def _methods(path: str, methods: set[str] | None) -> Iterator[Operation]:
    for method in sorted((methods or set()) - {"HEAD", "OPTIONS"}):
        yield method, path
