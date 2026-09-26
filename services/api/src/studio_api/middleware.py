"""Transverse middleware: CORS, rate limiting, security headers, request IDs.

These are intentionally simple and dependency-light (no Redis, no external
observability stack) so they stay safe to run in both local dev and the
Docker Compose deployment.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from studio_contracts.version import (
    CLIENT_FAMILIES,
    CLIENT_HEADER,
    CLIENT_STATUS_RECOMMENDED,
    LATEST_HEADER,
    UPDATE_HEADER,
    VERSION_HEADER,
)

from studio_api.compat import check_client, client_status, family_latest, family_minimum
from studio_api.observability import MetricsMiddleware
from studio_api.settings import Settings

logger = logging.getLogger(__name__)


class ClientVersionGuardMiddleware(BaseHTTPMiddleware):
    """C1 compatibility gate: a client declaring a build below the family
    minimum gets 426 `client_upgrade_required` with an update invitation.

    A client inside the grace window — at least the minimum, below the newest
    release — is served normally and flagged with an additive advisory header
    (`X-Studio-Client-Update: recommended`), never blocked. Pass-through by
    design for everything else — missing headers (pre-C1 clients), unknown
    families and unparsable versions never block, so an N-1 client keeps
    working untouched. Skips the unauthenticated probes and the signed GitHub
    webhook.
    """

    _SKIP_PATHS = {"/healthz", "/metrics", "/version", "/api/v1/github/webhook"}

    def __init__(self, app: Any, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self._SKIP_PATHS or not request.url.path.startswith("/api/v1"):
            return await call_next(request)
        client = (request.headers.get(CLIENT_HEADER) or "").lower()
        if client not in CLIENT_FAMILIES:
            return await call_next(request)
        client_version = request.headers.get(VERSION_HEADER)
        if check_client(client, client_version, self._settings):
            response = await call_next(request)
            if client_status(client, client_version, self._settings) == CLIENT_STATUS_RECOMMENDED:
                response.headers[UPDATE_HEADER] = CLIENT_STATUS_RECOMMENDED
                response.headers[LATEST_HEADER] = str(family_latest(self._settings, client))
            return response
        minimum = str(family_minimum(self._settings, client))
        latest = str(family_latest(self._settings, client))
        return Response(
            content=json.dumps(
                {
                    "detail": {
                        "error_code": "client_upgrade_required",
                        "client": client,
                        "client_version": client_version,
                        "minimum_supported": minimum,
                        "latest": latest,
                        "message": (
                            "This client version is no longer supported. "
                            "Please update to the latest release."
                        ),
                    }
                }
            ),
            status_code=426,
            media_type="application/json",
        )


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a stable request id to every request/response."""

    def __init__(self, app: Any, header_name: str = "x-request-id") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(self.header_name)
        if not request_id:
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[self.header_name] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline security headers. Not a substitute for CORS/auth."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        response.headers["permissions-policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory token-bucket rate limiter.

    Key precedence:
    1. Authenticated machine token hash (so two callers behind NAT are distinct).
    2. X-Forwarded-For first IP if present, then client host.

    This is per-process state; a real production deployment with multiple API
    replicas should switch to a shared store. The middleware stays intentionally
    simple so it does not become a dependency or scaling blocker for the V1
    single-node compose stack.
    """

    def __init__(
        self,
        app: Any,
        requests_per_minute: int = 120,
        burst: int = 20,
        webhook_requests_per_minute: int = 600,
        webhook_burst: int = 60,
    ) -> None:
        super().__init__(app)
        self.requests_per_minute = max(requests_per_minute, 1)
        self.burst = max(burst, 1)
        self.webhook_requests_per_minute = max(webhook_requests_per_minute, 1)
        self.webhook_burst = max(webhook_burst, 1)
        self._tokens: dict[str, float] = defaultdict(float)
        self._last_update: dict[str, float] = defaultdict(float)
        self._webhook_tokens: dict[str, float] = defaultdict(float)
        self._webhook_last_update: dict[str, float] = defaultdict(float)
        self._lock: Any = None

    async def _get_lock(self) -> Any:
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        return self._lock

    def _key(self, request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            if token:
                import hashlib

                return f"token:{hashlib.sha256(token.encode()).hexdigest()[:16]}"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        client = request.client
        host = client.host if client else "unknown"
        return f"ip:{host}"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in {"/healthz", "/metrics", "/version"}:
            return await call_next(request)

        # The GitHub webhook has its own bucket (DEC-0059): it carries no
        # machine token, so the default per-token key would collapse every
        # GitHub retry onto one IP bucket and throttle legitimate
        # redeliveries. Keyed per repository event stream instead.
        if request.url.path == "/api/v1/github/webhook":
            return await self._dispatch_with_bucket(
                request,
                call_next,
                self._webhook_tokens,
                self._webhook_last_update,
                self.webhook_requests_per_minute,
                self.webhook_burst,
                key_prefix="github-webhook",
            )
        return await self._dispatch_with_bucket(
            request,
            call_next,
            self._tokens,
            self._last_update,
            self.requests_per_minute,
            self.burst,
        )

    async def _dispatch_with_bucket(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
        tokens: dict[str, float],
        last_update: dict[str, float],
        requests_per_minute: int,
        burst: int,
        key_prefix: str = "",
    ) -> Response:
        key = key_prefix + self._key(request)
        now = time.monotonic()
        rate_per_second = requests_per_minute / 60.0
        async with await self._get_lock():
            last = last_update.get(key, now)
            current = min(
                burst,
                tokens.get(key, burst) + rate_per_second * (now - last),
            )
            if current < 1.0:
                return Response(
                    content='{"detail":"rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                    headers={"retry-after": str(int(60 / requests_per_minute) + 1)},
                )
            tokens[key] = current - 1.0
            last_update[key] = now

        return await call_next(request)


def setup_middleware(app: FastAPI, settings: Settings) -> None:
    """Register all transverse middleware in the correct order."""
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[
                settings.request_id_header,
                UPDATE_HEADER,
                LATEST_HEADER,
            ],
        )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)
    app.add_middleware(ClientVersionGuardMiddleware, settings=settings)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.rate_limit_requests_per_minute,
        burst=settings.rate_limit_burst,
        webhook_requests_per_minute=settings.github_webhook_rate_limit_per_minute,
        webhook_burst=settings.github_webhook_rate_limit_burst,
    )
    app.add_middleware(MetricsMiddleware)
