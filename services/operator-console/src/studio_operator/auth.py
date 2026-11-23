"""Operator authentication: TOTP gate, attempt lockout, own short-lived JWT.

The console issues and verifies its own token (`aud`/`iss` bound to the
console) signed with a secret distinct from the core API's, so a console
token is useless against the client API and vice versa. A token only carries
the operator's email; the operator list and the MFA secret are reloaded from
configuration on every request, so removing an operator or their secret
revokes access immediately.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from studio_operator.mfa import verify_totp
from studio_operator.settings import OperatorAccount, OperatorSettings, get_settings

ALGORITHM = "HS256"
AUDIENCE = "studio-operator-console"
ISSUER = "studio-operator-console"
TOKEN_TYPE = "operator_access"


def create_access_token(account: OperatorAccount, settings: OperatorSettings) -> str:
    issued_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": account.email,
        "aud": AUDIENCE,
        "iss": ISSUER,
        "type": TOKEN_TYPE,
        "jti": str(uuid.uuid4()),
        "mfa": True,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: OperatorSettings) -> str | None:
    """Operator email of a valid console token, or None on any failure."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["sub", "exp", "iat", "type", "aud", "iss"]},
        )
    except jwt.PyJWTError:
        return None
    if payload["type"] != TOKEN_TYPE or payload.get("mfa") is not True:
        return None
    subject = payload["sub"]
    return subject if isinstance(subject, str) and subject else None


@dataclass
class _AttemptState:
    failures: int = 0
    locked_until: float = 0.0


@dataclass
class AttemptTracker:
    """Per-operator failed-code counter with a temporary lockout (in memory:
    the console is a small, single-instance operator service)."""

    max_attempts: int
    lockout_seconds: int
    clock: Callable[[], float] = time.monotonic
    _states: dict[str, _AttemptState] = field(default_factory=dict)

    def _state(self, email: str) -> _AttemptState:
        return self._states.setdefault(email.lower(), _AttemptState())

    def locked_for(self, email: str) -> int:
        state = self._state(email)
        remaining = state.locked_until - self.clock()
        if remaining <= 0:
            if state.locked_until:
                state.locked_until = 0.0
                state.failures = 0
            return 0
        return math.ceil(remaining)

    def remaining_attempts(self, email: str) -> int:
        if self.locked_for(email):
            return 0
        return max(0, self.max_attempts - self._state(email).failures)

    def record_failure(self, email: str) -> int:
        state = self._state(email)
        state.failures += 1
        if state.failures >= self.max_attempts:
            state.locked_until = self.clock() + self.lockout_seconds
            return 0
        return self.max_attempts - state.failures

    def reset(self, email: str) -> None:
        self._states.pop(email.lower(), None)


@lru_cache(maxsize=8)
def _tracker(max_attempts: int, lockout_seconds: int) -> AttemptTracker:
    return AttemptTracker(max_attempts=max_attempts, lockout_seconds=lockout_seconds)


def get_attempt_tracker(
    settings: Annotated[OperatorSettings, Depends(get_settings)],
) -> AttemptTracker:
    """One lockout counter per (attempts, lockout) pair, so the configured
    values apply without a global mutable default."""
    return _tracker(settings.mfa_max_attempts, settings.mfa_lockout_minutes * 60)


def _refused() -> HTTPException:
    """Generic refusal: listed status and MFA configuration are never told
    apart to the caller (fiche C0, 'aucun détail par sécurité')."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "operator_not_allowed",
            "message": (
                "Ce compte n'est pas autorisé à utiliser la console, "
                "ou la MFA n'est pas configurée."
            ),
        },
    )


def _locked(seconds: int) -> HTTPException:
    minutes = max(1, math.ceil(seconds / 60))
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error_code": "mfa_locked",
            "message": f"Trop de codes incorrects. Réessayez dans {minutes} minute(s).",
            "retry_after_seconds": seconds,
        },
        headers={"Retry-After": str(seconds)},
    )


def authenticate(
    settings: OperatorSettings,
    tracker: AttemptTracker,
    email: str,
    code: str,
) -> tuple[OperatorAccount, str, int]:
    """Verify operator + MFA. Returns (account, token, ttl_seconds)."""
    account = settings.operator(email)
    if account is None or not account.has_mfa:
        raise _refused()

    locked_for = tracker.locked_for(account.email)
    if locked_for:
        raise _locked(locked_for)

    assert account.totp_secret is not None  # has_mfa
    if not verify_totp(account.totp_secret, code):
        remaining = tracker.record_failure(account.email)
        if remaining == 0:
            raise _locked(tracker.locked_for(account.email))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "mfa_invalid",
                "message": "Code incorrect.",
                "attempts_remaining": remaining,
            },
        )

    tracker.reset(account.email)
    return (
        account,
        create_access_token(account, settings),
        settings.token_ttl_minutes * 60,
    )


_BEARER = HTTPBearer(auto_error=False)


async def require_operator(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    settings: Annotated[OperatorSettings, Depends(get_settings)],
) -> OperatorAccount:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    email = decode_access_token(credentials.credentials, settings)
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    account = settings.operator(email)
    if account is None or not account.has_mfa:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return account
