from __future__ import annotations

import uuid
from datetime import UTC, datetime

import bcrypt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.security import generate_machine_token, hash_token


async def get_user_by_email(session: AsyncSession, email: str) -> UserModel | None:
    result = await session.execute(select(UserModel).where(UserModel.email == email))
    return result.scalar_one_or_none()


async def list_users(session: AsyncSession, query: str | None, limit: int) -> list[UserModel]:
    """Case-insensitive substring match on display name or email; `%` and `_`
    in `query` are literal."""
    stmt = select(UserModel)
    needle = (query or "").strip()
    if needle:
        pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(
            UserModel.display_name.ilike(pattern, escape="\\")
            | UserModel.email.ilike(pattern, escape="\\")
        )
    result = await session.execute(
        stmt.order_by(UserModel.display_name, UserModel.email).limit(limit)
    )
    return list(result.scalars().all())


async def users_by_id(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, UserModel]:
    if not ids:
        return {}
    result = await session.execute(select(UserModel).where(UserModel.id.in_(ids)))
    return {user.id: user for user in result.scalars()}


async def get_machine(session: AsyncSession, machine_id: uuid.UUID) -> MachineModel | None:
    return await session.get(MachineModel, machine_id)


async def list_machines(
    session: AsyncSession, owner_email: str | None = None
) -> list[tuple[MachineModel, UserModel]]:
    """Admin-facing listing: the machine UUID is only ever printed once at
    creation, so an operator that kept only the token has no other way to
    recover it (`get_machine_by_token` covers that case)."""
    stmt = select(MachineModel, UserModel).join(
        UserModel, MachineModel.owner_user_id == UserModel.id
    )
    if owner_email is not None:
        stmt = stmt.where(UserModel.email == owner_email)
    stmt = stmt.order_by(MachineModel.created_at)
    result = await session.execute(stmt)
    return [(machine, owner) for machine, owner in result.all()]


async def list_active_machines(
    session: AsyncSession, owner_user_id: uuid.UUID | None = None
) -> list[MachineModel]:
    """`owner_user_id=None` lists every owner's machines (admin only)."""
    stmt = select(MachineModel).where(MachineModel.credential_revoked_at.is_(None))
    if owner_user_id is not None:
        stmt = stmt.where(MachineModel.owner_user_id == owner_user_id)
    result = await session.execute(stmt.order_by(MachineModel.created_at))
    return list(result.scalars().all())


async def get_machine_by_token(
    session: AsyncSession, token: str
) -> tuple[MachineModel, UserModel] | None:
    """Resolve a machine from its opaque token by comparing the stored hash:
    the token itself is never logged nor persisted, only compared."""
    result = await session.execute(
        select(MachineModel, UserModel)
        .join(UserModel, MachineModel.owner_user_id == UserModel.id)
        .where(MachineModel.credential_hash == hash_token(token))
    )
    row = result.first()
    if row is None:
        return None
    return row[0], row[1]


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


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


async def set_user_password(session: AsyncSession, email: str, password: str) -> UserModel:
    user = await get_user_by_email(session, email)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    user.password_hash = _hash_password(password)
    await session.commit()
    await session.refresh(user)
    return user


_DUMMY_PASSWORD_HASH = _hash_password("studio-os-dummy-password")
"""Checked against when the email is unknown or has no password, so every
login attempt pays one bcrypt verification (no user-enumeration by timing)."""


async def verify_user_password(
    session: AsyncSession, email: str, password: str
) -> UserModel | None:
    user = await get_user_by_email(session, email)
    password_hash = user.password_hash if user is not None else None
    if password_hash is None:
        _verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    if not _verify_password(password, password_hash):
        return None
    return user


async def get_or_create_dashboard_machine(session: AsyncSession, user: UserModel) -> MachineModel:
    """Return a dedicated dashboard machine for the user, creating it if needed.

    The dashboard authenticates humans via JWT; the API still reasons in terms
    of machines, so a stable machine row acts as the dashboard's identity.
    """
    result = await session.execute(
        select(MachineModel).where(
            MachineModel.owner_user_id == user.id,
            MachineModel.display_name == "dashboard",
            MachineModel.credential_revoked_at.is_(None),
        )
    )
    machine = result.scalar_one_or_none()
    if machine is not None:
        return machine
    machine, _token = await create_machine(session, user.id, "dashboard")
    return machine
