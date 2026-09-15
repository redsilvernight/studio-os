"""Transverse middleware: CORS, rate limiting, security headers, request IDs.

These are intentionally simple and dependency-light (no Redis, no external
observability stack) so they stay safe to run in both local dev and the
Docker Compose deployment.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from studio_api.observability import MetricsMiddleware
from studio_api.settings import Settings

logger = logging.getLogger(__name__)


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
    ) -> None:
        super().__init__(app)
        self.requests_per_minute = max(requests_per_minute, 1)
        self.burst = max(burst, 1)
        self._tokens: dict[str, float] = defaultdict(float)
        self._last_update: dict[str, float] = defaultdict(float)
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
        if request.url.path in {"/healthz", "/metrics"}:
            return await call_next(request)

        key = self._key(request)
        now = time.monotonic()
        rate_per_second = self.requests_per_minute / 60.0
        async with await self._get_lock():
            last = self._last_update.get(key, now)
            tokens = min(
                self.burst,
                self._tokens.get(key, self.burst) + rate_per_second * (now - last),
            )
            if tokens < 1.0:
                return Response(
                    content='{"detail":"rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                    headers={"retry-after": str(int(60 / self.requests_per_minute) + 1)},
                )
            self._tokens[key] = tokens - 1.0
            self._last_update[key] = now

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
            expose_headers=[settings.request_id_header],
        )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.rate_limit_requests_per_minute,
        burst=settings.rate_limit_burst,
    )
    app.add_middleware(MetricsMiddleware)
