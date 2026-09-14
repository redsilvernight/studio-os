from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.security import hash_token
from studio_api.services.authz import Principal, load_principal

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
    authorization: Annotated[str | None, Header()] = None,
) -> MachineModel:
    """Machine auth per TECH/04_AUTH_SYNC_CONTRACT.md: opaque bearer token,
    verified by hash, independently revocable (DEC-0003)."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.removeprefix("Bearer ")
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
