from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.studio import StudioRole
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.jwt_auth import AccessClaims, decode_access_token
from studio_api.middleware import AUTHENTICATED_STATE_FLAG
from studio_api.openapi_meta import machine_bearer_scheme
from studio_api.security import hash_token
from studio_api.security_log import security_event
from studio_api.services.authz import (
    Principal,
    ensure_operator,
    ensure_studio_role,
    ensure_studio_writable,
    forbidden,
    is_studio_manager,
    load_principal,
)
from studio_api.services.launch_credentials import (
    ensure_rest_allowed,
    resolve_launch_credential,
)
from studio_api.settings import get_settings

DbSession = Annotated[AsyncSession, Depends(get_session)]

STUDIO_HEADER = "X-Studio-Id"
"""Client-requested active studio (DEC-0382), second after the JWT claim and
before `machines.studio_id`. Always revalidated against the user's
memberships by `resolve_active_studio`."""

JWT_STUDIO_STATE = "jwt_studio_id"
"""`request.state` attribute holding the optional `studio_id` claim of a JWT
principal, so `get_current_principal` can prefer it without decoding again."""


async def resolve_machine(session: AsyncSession, token: str) -> MachineModel | None:
    """Opaque bearer token -> `MachineModel`, verified by hash, independently
    revocable (DEC-0003). Shared by the HTTP auth dependency below and by
    `studio_mcp.auth` (DEC-0005: MCP calls services directly, but still needs
    this same lookup to identify its caller). A disabled or unverified owner
    blocks every machine it owns (DU-0/A, DEC-0110)."""
    token_hash = hash_token(token)
    result = await session.execute(
        select(MachineModel)
        .join(UserModel, UserModel.id == MachineModel.owner_user_id)
        .where(
            MachineModel.credential_hash == token_hash,
            MachineModel.credential_revoked_at.is_(None),
            UserModel.disabled_at.is_(None),
            UserModel.email_verified_at.is_not(None),
        )
    )
    machine = result.scalar_one_or_none()
    if machine is None:
        machine = await resolve_launch_credential(session, token)
    return machine


JWT_AUTH_VERSION_STATE = "jwt_auth_version"
"""`request.state` attribute holding the `auth_version` claim of a JWT
principal, so an open SSE stream can revalidate it (DEC-0110)."""


async def resolve_jwt_machine(session: AsyncSession, claims: AccessClaims) -> MachineModel | None:
    machine = await session.get(MachineModel, claims.machine_id)
    if machine is None or machine.credential_revoked_at is not None:
        return None
    if machine.owner_user_id != claims.user_id:
        return None
    user = await session.get(UserModel, claims.user_id)
    if user is None or not user.is_active or user.auth_version != claims.auth_version:
        return None
    return machine


async def get_current_machine(
    request: Request,
    session: DbSession,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(machine_bearer_scheme)] = None,
) -> MachineModel:
    """Machine auth: opaque bearer token or dashboard JWT, verified by hash or
    signature, independently revocable. A JWT is decoded to a dashboard machine
    id, then machine, owner state and `auth_version` are checked (DEC-0110)."""
    token = bearer.credentials if bearer is not None else None
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    machine: MachineModel | None = None
    if token.count(".") == 2:
        claims = decode_access_token(token, get_settings())
        if claims is not None:
            machine = await resolve_jwt_machine(session, claims)
            if machine is not None:
                setattr(request.state, JWT_AUTH_VERSION_STATE, claims.auth_version)
                if claims.studio_id is not None:
                    setattr(request.state, JWT_STUDIO_STATE, claims.studio_id)

    if machine is None:
        machine = await resolve_machine(session, token)
    if machine is None:
        security_event(
            "auth.bearer",
            outcome="failure",
            request=request,
            level=logging.WARNING,
            reason="invalid_or_revoked",
            path=request.url.path,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or revoked machine token")
    # Lets the rate limiter key this token on its own bucket from now on.
    setattr(request.state, AUTHENTICATED_STATE_FLAG, True)
    route = request.scope.get("route")
    ensure_rest_allowed(machine, request.method, getattr(route, "path", None))
    return machine


CurrentMachine = Annotated[MachineModel, Depends(get_current_machine)]


async def get_current_principal(
    request: Request, machine: CurrentMachine, session: DbSession
) -> Principal:
    """Studio + transverse role + resource ownership all start here (TECH/04
    Autorisation, DEC-0036, DEC-0382) — the owner of the authenticated machine,
    loaded once per request, in the active studio."""
    principal = await load_principal(session, machine, requested_studio_id(request))
    return replace(
        principal,
        human_authenticated=hasattr(request.state, JWT_AUTH_VERSION_STATE),
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def requested_studio_id(request: Request) -> uuid.UUID | None:
    """Active-studio request, in the documented priority order: JWT
    `studio_id` claim, then `X-Studio-Id` header. The machine's own `studio_id`
    is only a preference resolved by `load_principal`. `None` lets
    `resolve_active_studio` apply its default, so a client that sends nothing
    (every N-1 client) keeps its previous reach."""
    claim: uuid.UUID | None = getattr(request.state, JWT_STUDIO_STATE, None)
    if claim is not None:
        return claim
    header = request.headers.get(STUDIO_HEADER)
    if header is None or not header.strip():
        return None
    try:
        return uuid.UUID(header.strip())
    except ValueError:
        raise forbidden("studio", "read") from None


def require_studio_role(min_role: StudioRole) -> Callable[..., Awaitable[Principal]]:
    """Studio management gate for routers (DEC-0382): `owner`/`admin` for
    studio administration, `member`+ for writes, `viewer`+ for reads."""

    async def _dependency(principal: CurrentPrincipal) -> Principal:
        ensure_studio_role(principal, min_role)
        return principal

    return _dependency


async def require_operator(principal: CurrentPrincipal) -> Principal:
    """Instance-operation gate (`users.is_operator`). Never a content read."""
    ensure_operator(principal)
    return principal


async def require_project_provisioner(principal: CurrentPrincipal) -> UserModel:
    """Project creation gate (DEC-0012): an `owner`/`admin` of the active studio
    or an account `developer`. Runs as a dependency so its 403 still precedes
    body validation. A studio scheduled for deletion is read-only (0051)."""
    ensure_studio_writable(principal)
    if is_studio_manager(principal) or principal.role == Role.DEVELOPER:
        return principal.user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
