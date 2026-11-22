"""Fail-closed access registry of every HTTP operation (DEC-0103 §12).

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
    ("GET", "/version"): "public",
    ("POST", "/api/v1/auth/token"): "public",
    ("POST", "/api/v1/auth/refresh"): "public",
    ("POST", "/api/v1/auth/logout"): "public",
    ("POST", "/api/v1/auth/register"): "public",
    ("POST", "/api/v1/auth/resend-verification"): "public",
    ("POST", "/api/v1/auth/verify-email"): "public",
    ("POST", "/api/v1/auth/forgot-password"): "public",
    ("POST", "/api/v1/auth/reset-password"): "public",
    ("POST", "/api/v1/invitations/preview"): "public",
    ("POST", "/api/v1/github/webhook"): "public",
    ("GET", "/openapi.json"): "public",
    ("GET", "/docs"): "public",
    ("GET", "/docs/oauth2-redirect"): "public",
    ("GET", "/redoc"): "public",
    # Instance: role-guarded provisioning, no existing project's data.
    ("POST", "/api/v1/projects"): "instance",
    ("GET", "/api/v1/internal/infra-measurements"): "instance",
    ("GET", "/api/v1/users"): "instance",
    ("GET", "/api/v1/studio/members"): "instance",
    ("POST", "/api/v1/users"): "instance",
    ("POST", "/api/v1/users/{user_id}/disable"): "instance",
    ("POST", "/api/v1/users/{user_id}/enable"): "instance",
    ("POST", "/api/v1/users/{user_id}/revoke-sessions"): "instance",
    ("GET", "/api/v1/users/{user_id}/memberships"): "instance",
    # Studio lifecycle (0051): owner-only, tenant-level, never a project's data.
    ("POST", "/api/v1/studios/{studio_id}/exports"): "instance",
    ("GET", "/api/v1/studios/{studio_id}/exports/{export_id}"): "instance",
    ("POST", "/api/v1/studios/{studio_id}/deletion"): "instance",
    ("DELETE", "/api/v1/studios/{studio_id}/deletion"): "instance",
