"""Human dashboard JWT authentication (DASH-4).

A signed short-lived JWT carries a dashboard machine id. It is accepted as an
alternative to the opaque machine bearer token on every API endpoint, so the
dashboard can authenticate a human user without changing the core machine-based
authorization model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.settings import Settings

ALGORITHM = "HS256"

DEFAULT_JWT_SECRET = "change-me-in-production"
MIN_JWT_SECRET_BYTES = 32


def is_weak_jwt_secret(secret: str) -> bool:
    """Default placeholder or shorter than the RFC 7518 section 3.2 minimum
    for HS256. Warning-only (DEC-0060): refusing to start would break local
    dev and CI, which intentionally run on the placeholder."""
    return secret == DEFAULT_JWT_SECRET or len(secret.encode()) < MIN_JWT_SECRET_BYTES


def create_access_token(user: UserModel, machine: MachineModel, settings: Settings) -> str:
    """Issue a JWT bound to a user and their dashboard machine."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "machine_id": str(machine.id),
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any] | None:
    """Decode and validate a JWT access token. Returns None on any failure."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
