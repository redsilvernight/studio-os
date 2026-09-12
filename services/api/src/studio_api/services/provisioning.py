from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.security import generate_machine_token, hash_token


async def get_user_by_email(session: AsyncSession, email: str) -> UserModel | None:
    result = await session.execute(select(UserModel).where(UserModel.email == email))
    return result.scalar_one_or_none()


async def get_machine(session: AsyncSession, machine_id: uuid.UUID) -> MachineModel | None:
    return await session.get(MachineModel, machine_id)


async def bootstrap_admin(session: AsyncSession, display_name: str, email: str) -> UserModel:
    """CLI-only entry point (DEC-0011): creates the very first admin before any
    machine token exists to authenticate an API call."""
    existing = await session.execute(select(UserModel).where(UserModel.role == "admin"))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "an admin user already exists")
    return await create_user(session, display_name, email, role="admin")


async def create_user(session: AsyncSession, display_name: str, email: str, role: str) -> UserModel:
    if await get_user_by_email(session, email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    user = UserModel(display_name=display_name, email=email, role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def create_machine(
    session: AsyncSession, owner_user_id: uuid.UUID, display_name: str
) -> tuple[MachineModel, str]:
    owner = await session.get(UserModel, owner_user_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "owner user not found")
    token = generate_machine_token()
    machine = MachineModel(
        owner_user_id=owner_user_id,
        display_name=display_name,
        credential_hash=hash_token(token),
    )
    session.add(machine)
    await session.commit()
    await session.refresh(machine)
    return machine, token


async def revoke_machine(session: AsyncSession, machine: MachineModel) -> MachineModel:
    if machine.credential_revoked_at is None:
        machine.credential_revoked_at = datetime.now(UTC)
        machine.version += 1
        await session.commit()
        await session.refresh(machine)
    return machine
