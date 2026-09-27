"""Rotating dashboard refresh tokens (DEC-0142, complements DEC-0110).

The access JWT stays short-lived and in memory. A client that asks for it at
login (the desktop) also gets an opaque 256-bit refresh secret; only its
SHA-256 is stored. Every refresh consumes the secret with a single
conditional UPDATE and issues a new one in the same family, so of two
concurrent refreshes exactly one wins. A consumed secret presented again is
treated as theft: the whole family is revoked.

Revocation needs no hook of its own: a family is bound to the User's
`auth_version` at login, so everything that already invalidates JWTs
(password change/reset, disable, role change, revoke-sessions) also ends it.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.refresh_token import RefreshTokenModel
from studio_api.db.models.user import UserModel
from studio_api.security import hash_token
from studio_api.security_log import security_event
from studio_api.settings import Settings


@dataclass(frozen=True)
class IssuedRefreshToken:
    secret: str
    expires_at: datetime


@dataclass(frozen=True)
class RefreshedSession:
    user: UserModel
    machine: MachineModel
    refresh: IssuedRefreshToken


def _sliding_expiry(now: datetime, absolute: datetime, settings: Settings) -> datetime:
    return min(now + timedelta(days=settings.refresh_token_sliding_days), absolute)


def _new_row(
    session: AsyncSession,
    *,
    user: UserModel,
    machine: MachineModel,
    family_id: uuid.UUID,
    auth_version: int,
    absolute_expires_at: datetime,
    now: datetime,
    settings: Settings,
) -> IssuedRefreshToken:
    secret = secrets.token_urlsafe(32)
    expires_at = _sliding_expiry(now, absolute_expires_at, settings)
    session.add(
        RefreshTokenModel(
            user_id=user.id,
            machine_id=machine.id,
            family_id=family_id,
            token_hash=hash_token(secret),
            auth_version=auth_version,
            created_at=now,
            expires_at=expires_at,
            absolute_expires_at=absolute_expires_at,
        )
    )
    return IssuedRefreshToken(secret=secret, expires_at=expires_at)


async def issue(
    session: AsyncSession, user: UserModel, machine: MachineModel, settings: Settings
) -> IssuedRefreshToken:
    """Start a new family at login. The caller commits."""
    now = datetime.now(UTC)
    return _new_row(
        session,
        user=user,
        machine=machine,
        family_id=uuid.uuid4(),
        auth_version=user.auth_version,
        absolute_expires_at=now + timedelta(days=settings.refresh_token_absolute_days),
        now=now,
        settings=settings,
    )


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshTokenModel)
        .where(RefreshTokenModel.family_id == family_id, RefreshTokenModel.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def _session_owner(
    session: AsyncSession, row: RefreshTokenModel
) -> tuple[UserModel, MachineModel] | None:
    """Same checks as a JWT principal (DEC-0110), against the family's
    `auth_version`."""
    machine = await session.get(MachineModel, row.machine_id)
    if machine is None or machine.credential_revoked_at is not None:
        return None
    if machine.owner_user_id != row.user_id:
        return None
    user = await session.get(UserModel, row.user_id)
    if user is None or not user.is_active or user.auth_version != row.auth_version:
        return None
    return user, machine


async def rotate(
    session: AsyncSession, secret: str, settings: Settings, request: Request | None = None
) -> RefreshedSession | None:
    """Consume `secret` and issue its successor. None on any failure (unknown,
    expired, revoked, reused, owner no longer valid); the cause is only logged."""
    now = datetime.now(UTC)
    token_hash = hash_token(secret)
    consumed = await session.execute(
        update(RefreshTokenModel)
        .where(
            RefreshTokenModel.token_hash == token_hash,
            RefreshTokenModel.consumed_at.is_(None),
            RefreshTokenModel.revoked_at.is_(None),
            RefreshTokenModel.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(RefreshTokenModel)
    )
    row = consumed.scalar_one_or_none()
    if row is None:
        await _refuse_unconsumable(session, token_hash, now, request)
        return None

    owner = await _session_owner(session, row)
    if owner is None:
        await _revoke_family(session, row.family_id, now)
        await session.commit()
        security_event(
            "auth.refresh",
            outcome="failure",
            request=request,
            level=logging.WARNING,
            reason="session_revoked",
            user_id=row.user_id,
        )
        return None
    user, machine = owner
    refresh = _new_row(
        session,
        user=user,
        machine=machine,
        family_id=row.family_id,
        auth_version=row.auth_version,
        absolute_expires_at=row.absolute_expires_at,
        now=now,
        settings=settings,
    )
    await session.commit()
    security_event(
        "auth.refresh", outcome="success", request=request, user_id=user.id, machine_id=machine.id
    )
    return RefreshedSession(user=user, machine=machine, refresh=refresh)


async def _refuse_unconsumable(
    session: AsyncSession, token_hash: str, now: datetime, request: Request | None
) -> None:
    result = await session.execute(
        select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    reason = "unknown"
    if row is not None:
        if row.revoked_at is not None:
            reason = "revoked"
        elif row.consumed_at is not None:
            # Replay of a rotated secret: whoever holds the family, it leaked.
            reason = "reused"
            await _revoke_family(session, row.family_id, now)
            await session.commit()
        else:
            reason = "expired"
    security_event(
        "auth.refresh",
        outcome="failure",
        request=request,
        level=logging.WARNING,
        reason=reason,
        user_id=row.user_id if row is not None else None,
    )


async def revoke(session: AsyncSession, secret: str, request: Request | None = None) -> None:
    """Logout: end the family of `secret`, whatever its state. Silent when the
    secret is unknown, so the answer reveals nothing."""
    result = await session.execute(
        select(RefreshTokenModel.family_id, RefreshTokenModel.user_id).where(
            RefreshTokenModel.token_hash == hash_token(secret)
        )
    )
    found = result.one_or_none()
    if found is None:
        return
    await _revoke_family(session, found.family_id, datetime.now(UTC))
    await session.commit()
    security_event("auth.logout", outcome="success", request=request, user_id=found.user_id)
