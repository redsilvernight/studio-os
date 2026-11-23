"""Anti-abuse guards for public self-registration (S5).

Three layers, all driven by `Settings`:

* a sliding-window quota per client IP and per e-mail domain, so one host or
  one provider cannot mass-create pending accounts;
* a configurable list of disposable (throw-away) e-mail domains;
* a bot-protection hook (`RegistrationBotProtection`). Only a permissive
  implementation ships here: no third-party service is wired, and the hook is
  disabled by default. Turning it on without wiring a provider fails closed
  instead of accepting everyone.

Counters live in memory, per process (DEC-0106): no schema change, no
migration. A multi-replica deployment needs a shared atomic store before it
can enforce these limits across replicas.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal, Protocol

from fastapi import Depends, HTTPException, Request, status

from studio_api.middleware import CLIENT_IP_STATE
from studio_api.security_log import email_digest, security_event
from studio_api.settings import Settings, get_settings

LimitScope = Literal["ip", "domain"]


@dataclass(frozen=True)
class RegistrationLimits:
    """How many registrations a scope may start inside `window_seconds`.
    A maximum of 0 disables that scope."""

    per_ip: int
    per_domain: int
    window_seconds: int

    @classmethod
    def from_settings(cls, settings: Settings) -> RegistrationLimits:
        return cls(
            per_ip=settings.registration_ip_limit,
            per_domain=settings.registration_domain_limit,
            window_seconds=settings.registration_limit_window_seconds,
        )


@dataclass(frozen=True)
class LimitVerdict:
    scope: LimitScope
    retry_after_seconds: int


class RegistrationGuard:
    """Bounded, in-memory sliding-window counters.

    `check` is synchronous and never awaits, so a check-and-record pair is
    atomic on the event loop. Keys are `(limits, scope, value)`: two settings
    profiles never share a counter, which also keeps tests independent.
    """

    MAX_TRACKED_KEYS = 10_000

    def __init__(self) -> None:
        self._hits: dict[tuple[RegistrationLimits, LimitScope, str], deque[float]] = {}

    def check(
        self,
        limits: RegistrationLimits,
        *,
        client_ip: str | None,
        domain: str,
        now: float | None = None,
    ) -> LimitVerdict | None:
        """Return the exceeded scope, or None when the request may proceed.
        An allowed call consumes one slot in every enabled scope."""
        moment = time.monotonic() if now is None else now
        scopes: tuple[tuple[LimitScope, str | None, int], ...] = (
            ("ip", client_ip, limits.per_ip),
            ("domain", domain, limits.per_domain),
        )
        for scope, value, maximum in scopes:
            if maximum <= 0 or not value:
                continue
            bucket = self._bucket(limits, scope, value, moment)
            if len(bucket) >= maximum:
                retry = max(1, math.ceil(bucket[0] + limits.window_seconds - moment))
                return LimitVerdict(scope=scope, retry_after_seconds=retry)
        for scope, value, maximum in scopes:
            if maximum > 0 and value:
                self._bucket(limits, scope, value, moment).append(moment)
        return None

    def _bucket(
        self,
        limits: RegistrationLimits,
        scope: LimitScope,
        value: str,
        now: float,
    ) -> deque[float]:
        key = (limits, scope, value)
        bucket = self._hits.get(key)
        if bucket is None:
            bucket = deque()
            self._hits[key] = bucket
            while len(self._hits) > self.MAX_TRACKED_KEYS:
                self._hits.pop(next(iter(self._hits)))
        cutoff = now - limits.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        return bucket


class RegistrationBotProtection(Protocol):
    """Hook for an anti-robot check. Implementations either return normally
    (the request may proceed) or raise an `HTTPException`."""

    enabled: bool

    async def verify(self, request: Request, email: str) -> None: ...


class AllowAllBotProtection:
    """Default implementation: no provider wired, nothing to check.

    A real provider (captcha, proof-of-work, vendor API) plugs in here and is
    enabled with `STUDIO_REGISTRATION_BOT_PROTECTION_ENABLED`."""

    enabled = False

    async def verify(self, request: Request, email: str) -> None:
        return None


_allow_all = AllowAllBotProtection()
_guard = RegistrationGuard()


def get_registration_guard() -> RegistrationGuard:
    return _guard


def get_registration_bot_protection(
    settings: Settings = Depends(get_settings),
) -> RegistrationBotProtection:
    if settings.registration_bot_protection_enabled:
        # Fail closed: enabling the hook without wiring a provider must not
        # degrade to "everyone accepted".
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "registration_bot_protection_unavailable"},
        )
    return _allow_all


def email_domain(email: str) -> str:
    return email.strip().lower().rsplit("@", 1)[-1]


def request_client_ip(request: Request) -> str | None:
    """Trusted-proxy-aware IP resolved once by `RateLimitMiddleware`."""
    resolved = getattr(request.state, CLIENT_IP_STATE, None)
    if isinstance(resolved, str) and resolved:
        return resolved
    return request.client.host if request.client else None


def disposable_domains(settings: Settings) -> tuple[str, ...]:
    return tuple(
        domain.strip().lower()
        for domain in settings.registration_disposable_email_domains.split(",")
        if domain.strip()
    )


def is_disposable_domain(domain: str, settings: Settings) -> bool:
    return any(
        domain == blocked or domain.endswith(f".{blocked}")
        for blocked in disposable_domains(settings)
    )


def reject_disposable_domain(*, request: Request, settings: Settings, email: str) -> None:
    domain = email_domain(email)
    if not is_disposable_domain(domain, settings):
        return
    security_event(
        "registration.blocked",
        outcome="blocked",
        request=request,
        reason="disposable_domain",
        email_digest=email_digest(email),
        email_domain=domain,
    )
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail={"error_code": "email_domain_not_allowed"},
    )


def enforce_registration_limits(
    *,
    request: Request,
    settings: Settings,
    guard: RegistrationGuard,
    email: str,
) -> None:
    verdict = guard.check(
        RegistrationLimits.from_settings(settings),
        client_ip=request_client_ip(request),
        domain=email_domain(email),
    )
    if verdict is None:
        return
    security_event(
        "registration.blocked",
        outcome="blocked",
        request=request,
        reason="rate_limited",
        scope=verdict.scope,
        email_digest=email_digest(email),
    )
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"error_code": "registration_rate_limited", "scope": verdict.scope},
        headers={"Retry-After": str(verdict.retry_after_seconds)},
    )
