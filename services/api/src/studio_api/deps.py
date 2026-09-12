from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.machine import MachineModel
from studio_api.db.session import get_session
from studio_api.security import hash_token

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_machine(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> MachineModel:
    """Machine auth per TECH/04_AUTH_SYNC_CONTRACT.md: opaque bearer token,
    verified by hash, independently revocable (DEC-0003)."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.removeprefix("Bearer ")
    token_hash = hash_token(token)
    result = await session.execute(
        select(MachineModel).where(
            MachineModel.credential_hash == token_hash,
            MachineModel.credential_revoked_at.is_(None),
        )
    )
    machine = result.scalar_one_or_none()
    if machine is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or revoked machine token")
    return machine


CurrentMachine = Annotated[MachineModel, Depends(get_current_machine)]
