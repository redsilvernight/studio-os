from __future__ import annotations

import os
import uuid

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.deps import resolve_machine
from studio_api.services.authz import forbidden

STUDIO_HEADER = "X-Studio-Id"
"""HTTP transport: the studio the caller acts in, same header and same
priority as the REST API (DEC-0382)."""

STUDIO_ENV = "STUDIO_MCP_STUDIO_ID"
"""stdio transport equivalent of `STUDIO_HEADER`: a single local process has
no HTTP request to read the active studio from."""


class McpAuthError(Exception):
    """Caller identity could not be established — see DEC-0023 (MCP auth)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.error_code = "unauthenticated"
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"error_code": self.error_code, "message": self.message}


def _extract_token(ctx: Context) -> str | None:
    """HTTP transport (multi-client, deployed behind Caddy): read the caller's
    own `Authorization: Bearer` header, same as the API — a missing or
    malformed header is rejected outright, never falling back to the process
    env var. stdio transport (single local process, no HTTP request at all,
    so `ctx.headers is None`) falls back to `STUDIO_MCP_MACHINE_TOKEN`."""
    headers = ctx.headers
    if headers is not None:
        auth_header = headers.get("authorization") or headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.removeprefix("Bearer ")
        return None
    return os.environ.get("STUDIO_MCP_MACHINE_TOKEN")


async def authenticate(ctx: Context, session: AsyncSession) -> MachineModel:
    """Resolve the calling machine for a tool invocation, per DEC-0023. Uses
    the exact same hash lookup as the HTTP API (`studio_api.deps.resolve_machine`)
    — a token is never trusted without that check."""
    token = _extract_token(ctx)
    if token is None:
        raise McpAuthError("missing machine token")
    machine = await resolve_machine(session, token)
    if machine is None:
        raise McpAuthError("invalid or revoked machine token")
    return machine


def requested_studio_id(ctx: Context) -> uuid.UUID | None:
    """The studio the caller asks to act in (DEC-0382), read exactly like the
    REST dependency: `X-Studio-Id` over HTTP, `STUDIO_MCP_STUDIO_ID` on stdio
    (no request at all). `None` lets `load_principal` apply its default. A
    malformed value answers the same 403 as the API, and a studio the caller
    is not a member of is refused by `load_principal` — never by a tool."""
    headers = ctx.headers
    raw: str | None
    if headers is not None:
        raw = headers.get(STUDIO_HEADER) or headers.get(STUDIO_HEADER.lower())
    else:
        raw = os.environ.get(STUDIO_ENV)
    if raw is None or not raw.strip():
        return None
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        raise forbidden("studio", "read") from None
