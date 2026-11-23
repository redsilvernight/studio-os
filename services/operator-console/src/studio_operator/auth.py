"""Operator authentication: TOTP gate, attempt lockout, own short-lived JWT.

The console issues and verifies its own token (`aud`/`iss` bound to the
console) signed with a secret distinct from the core API's, so a console
token is useless against the client API and vice versa. A token only carries
the operator's email; the operator list and the MFA secret are reloaded from
configuration on every request, so removing an operator or their secret
revokes access immediately.
"""

from __future__ import annotations

import base64
import math
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any
from urllib.parse import quote, urlencode

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from studio_operator.mfa import verify_totp
from studio_operator.passwords import verify_password
from studio_operator.secrets_store import SecretStore, get_secret_store
from studio_operator.settings import OperatorAccount, OperatorSettings, get_settings

ALGORITHM = "HS256"
AUDIENCE = "studio-operator-console"
ISSUER = "studio-operator-console"
TOKEN_TYPE = "operator_access"
OTP_ISSUER = "Studio OS Operator"


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
        return self._states.setdefault(email.strip().lower(), _AttemptState())

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
        self._states.pop(email.strip().lower(), None)


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
    """Generic refusal: unknown account, wrong password and missing MFA are
    never told apart to the caller (fiche C0, 'aucun détail par sécurité')."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "operator_not_allowed",
            "message": (
                "Accès refusé. Ce compte n'est pas autorisé à utiliser la console, "
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


def effective_secret(account: OperatorAccount, store: SecretStore) -> str | None:
    """Enrolled secret first (state file), then the configured one."""
    stored = store.active_secret(account.email)
    if stored:
        return stored
    if account.totp_secret and account.totp_secret.strip():
        return account.totp_secret.strip()
    return None


def authenticate(
    settings: OperatorSettings,
    tracker: AttemptTracker,
    store: SecretStore,
    email: str,
    password: str,
    code: str,
) -> tuple[OperatorAccount, str, int]:
    """Verify account + password + TOTP. Returns (account, token, ttl_seconds).

    A wrong password, an unknown account and a missing MFA share one refusal
    and the same failure counter; only a valid password with a wrong code
    answers `mfa_invalid` (so the UI can show the attempts left, as fiche C0
    asks)."""
    locked_for = tracker.locked_for(email)
    if locked_for:
        raise _locked(locked_for)

    account = settings.operator(email)
    password_ok = verify_password(password, account.password_hash if account else None)
    secret = effective_secret(account, store) if account else None
    if account is None or not password_ok or secret is None:
        remaining = tracker.record_failure(email)
        if remaining == 0:
            raise _locked(tracker.locked_for(email))
        raise _refused()

    if not verify_totp(secret, code):
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


def _new_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def otpauth_uri(account: OperatorAccount, secret: str) -> str:
    label = quote(f"{OTP_ISSUER}:{account.email}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": OTP_ISSUER,
            "algorithm": "SHA1",
            "digits": 6,
            "period": 30,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def start_enrollment(
    settings: OperatorSettings,
    tracker: AttemptTracker,
    store: SecretStore,
    email: str,
    password: str,
) -> tuple[OperatorAccount, str, str, int]:
    """Password-gated enrollment start. Returns (account, secret, uri, ttl)."""
    locked_for = tracker.locked_for(email)
    if locked_for:
        raise _locked(locked_for)

    account = settings.operator(email)
    if account is None or not verify_password(password, account.password_hash if account else None):
        remaining = tracker.record_failure(email)
        if remaining == 0:
            raise _locked(tracker.locked_for(email))
        raise _refused()
    if effective_secret(account, store) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "mfa_already_active",
                "message": "La MFA est déjà activée pour ce compte.",
            },
        )

    tracker.reset(account.email)
    secret = _new_secret()
    ttl_seconds = settings.enrollment_ttl_minutes * 60
    store.start_pending(account.email, secret, ttl_seconds=ttl_seconds)
    return account, secret, otpauth_uri(account, secret), ttl_seconds


def confirm_enrollment(
    settings: OperatorSettings,
    tracker: AttemptTracker,
    store: SecretStore,
    email: str,
    code: str,
) -> OperatorAccount:
    """Confirm the pending secret with a first 6-digit code, then activate it."""
    locked_for = tracker.locked_for(email)
    if locked_for:
        raise _locked(locked_for)

    account = settings.operator(email)
    if account is None:
        raise _refused()
    if effective_secret(account, store) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "mfa_already_active",
                "message": "La MFA est déjà activée pour ce compte.",
            },
        )
    pending = store.pending_secret(account.email)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "enrollment_expired",
                "message": "Aucun enrôlement en cours. Recommencez la configuration.",
            },
        )
    if not verify_totp(pending, code):
        remaining = tracker.record_failure(account.email)
        if remaining == 0:
            store.clear_pending(account.email)
            raise _locked(tracker.locked_for(account.email))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "mfa_invalid",
                "message": "Code incorrect.",
                "attempts_remaining": remaining,
            },
        )

    store.activate(account.email, pending)
    tracker.reset(account.email)
    return account


_BEARER = HTTPBearer(auto_error=False)


async def require_operator(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    settings: Annotated[OperatorSettings, Depends(get_settings)],
    store: Annotated[SecretStore, Depends(get_secret_store)],
) -> OperatorAccount:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    email = decode_access_token(credentials.credentials, settings)
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    account = settings.operator(email)
    if account is None or account.password_hash is None or effective_secret(account, store) is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return account
