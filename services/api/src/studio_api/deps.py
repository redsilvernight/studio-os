from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.jwt_auth import decode_access_token
from studio_api.openapi_meta import machine_bearer_scheme
from studio_api.security import hash_token
from studio_api.services.authz import Principal, load_principal
from studio_api.settings import get_settings

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def resolve_machine(session: AsyncSession, token: str) -> MachineModel | None:
    """Opaque bearer token -> `MachineModel`, verified by hash, independently
    revocable (DEC-0003). Shared by the HTTP auth dependency below and by
    `studio_mcp.auth` (DEC-0005: MCP calls services directly, but still needs
    this same lookup to identify its caller)."""
    token_hash = hash_token(token)
    result = await session.execute(
        select(MachineModel).where(
            MachineModel.credential_hash == token_hash,
            MachineModel.credential_revoked_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_current_machine(
    session: DbSession,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(machine_bearer_scheme)] = None,
) -> MachineModel:
    """Machine auth: opaque bearer token or dashboard JWT, verified by hash or
    signature, independently revocable. A JWT is decoded to a dashboard machine
    id; the machine row is still verified (it may have been revoked)."""
    token = bearer.credentials if bearer is not None else None
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    # Dashboard JWT: three dot-separated segments, decode to machine id.
    if token.count(".") == 2:
        payload = decode_access_token(token, get_settings())
        if payload is not None:
            machine_id = payload.get("machine_id")
            if machine_id:
                from uuid import UUID

                try:
                    machine = await session.get(MachineModel, UUID(machine_id))
                except ValueError:
                    machine = None
                if machine is not None and machine.credential_revoked_at is None:
                    return machine

    machine = await resolve_machine(session, token)
    if machine is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or revoked machine token")
    return machine


CurrentMachine = Annotated[MachineModel, Depends(get_current_machine)]


async def get_current_principal(machine: CurrentMachine, session: DbSession) -> Principal:
    """Transverse role + resource ownership both start here (TECH/04
    Autorisation, DEC-0036) — the owner of the authenticated machine, loaded
    once per request."""
    return await load_principal(session, machine)


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_roles(*roles: Role) -> Callable[..., Awaitable[UserModel]]:
    """Role gate for provisioning endpoints (DEC-0012): a request's user
    identity is the owner of its authenticated machine — there is no separate
    user-level HTTP auth in v1. Applied only to the new provisioning
    endpoints, not retrofitted onto existing write endpoints (that would
    change their observable behavior and needs its own contract change)."""
    allowed = {role.value for role in roles}

    async def _dependency(machine: CurrentMachine, session: DbSession) -> UserModel:
        user = await session.get(UserModel, machine.owner_user_id)
        if user is None or user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user

    return _dependency
