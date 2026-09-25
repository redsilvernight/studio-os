"""Human dashboard JWT authentication (DASH-4).

A signed short-lived JWT carries a dashboard machine id. It is accepted as an
alternative to the opaque machine bearer token on every API endpoint, so the
dashboard can authenticate a human user without changing the core machine-based
authorization model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.settings import Settings

ALGORITHM = "HS256"

DEFAULT_JWT_SECRET = "change-me-in-production"
# Placeholders shipped in the repo (settings default, docker/.env.example).
PLACEHOLDER_JWT_SECRETS = frozenset(
    {DEFAULT_JWT_SECRET, "change-me-to-a-long-random-string-min-32-bytes"}
)
MIN_JWT_SECRET_BYTES = 32


def is_weak_jwt_secret(secret: str) -> bool:
    """A shipped placeholder or shorter than the RFC 7518 section 3.2 minimum
    for HS256. Fatal at startup in production, warning-only when
    STUDIO_ENVIRONMENT is dev/test (local dev and CI run on the placeholder)."""
    return secret in PLACEHOLDER_JWT_SECRETS or len(secret.encode()) < MIN_JWT_SECRET_BYTES


def access_token_lifetime_seconds(settings: Settings) -> int:
    return settings.jwt_access_token_expire_minutes * 60


def create_access_token(user: UserModel, machine: MachineModel, settings: Settings) -> str:
    """Issue a JWT bound to a user, their dashboard machine and the user's
    current `auth_version` (DEC-0110). Email and role are never carried: the
    server reloads them, a client reads them from `GET /auth/me`."""
    issued_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "machine_id": str(machine.id),
        "session_id": str(uuid.uuid4()),
        "auth_version": user.auth_version,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=access_token_lifetime_seconds(settings)),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    machine_id: uuid.UUID
    auth_version: int


def decode_access_token(token: str, settings: Settings) -> AccessClaims | None:
    """Verify signature, expiry and shape of a DEC-0110 access token. Returns
    None on any failure, including a pre-cutover token without `auth_version`."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "machine_id", "auth_version", "exp", "iat", "type"]},
        )
    except jwt.PyJWTError:
        return None
    auth_version = payload["auth_version"]
    if payload["type"] != "access" or type(auth_version) is not int:
        return None
    try:
        return AccessClaims(
            user_id=uuid.UUID(str(payload["sub"])),
            machine_id=uuid.UUID(str(payload["machine_id"])),
            auth_version=auth_version,
        )
    except ValueError:
        return None
