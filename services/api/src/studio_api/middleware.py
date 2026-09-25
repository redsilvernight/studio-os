"""Transverse middleware: CORS, rate limiting, security headers, request IDs.

These are intentionally simple and dependency-light (no Redis, no external
observability stack) so they stay safe to run in both local dev and the
Docker Compose deployment.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import time
import uuid
from collections import OrderedDict, defaultdict
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


IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# Set by the auth dependency (`deps.get_current_machine`) once the bearer token
# has actually been verified; the rate limiter only trusts a token as a bucket
# key after seeing this flag (scope["state"] is shared with the middleware).
AUTHENTICATED_STATE_FLAG = "bearer_authenticated"


def parse_trusted_proxies(spec: str) -> tuple[IPNetwork, ...]:
    """Comma-separated IPs/CIDRs. An invalid entry fails at startup."""
    return tuple(
        ipaddress.ip_network(part.strip(), strict=False) for part in spec.split(",") if part.strip()
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory token-bucket rate limiter.

    Key precedence:
    1. Hash of a bearer token this process has already seen authenticate
       successfully (so two callers behind NAT are distinct). An unverified
       token never gets its own bucket: rotating fake tokens stays keyed on IP.
    2. Client IP. `X-Forwarded-For` is honored only when the direct peer is a
       trusted proxy (`STUDIO_TRUSTED_PROXIES`), and then the rightmost hop not
       itself a trusted proxy is used — a spoofed left part is ignored.

    `/api/v1/auth/*` has its own stricter bucket, always keyed on client IP,
    except the authenticated identity read `/api/v1/auth/me`.

    This is per-process state; a real production deployment with multiple API
    replicas should switch to a shared store. The middleware stays intentionally
    simple so it does not become a dependency or scaling blocker for the V1
    single-node compose stack.
    """

    AUTH_PATH_PREFIX = "/api/v1/auth/"
    AUTHENTICATED_AUTH_PATHS = frozenset({"/api/v1/auth/me"})
    MAX_AUTHENTICATED_TOKENS = 10_000

    def __init__(
        self,
        app: Any,
        requests_per_minute: int = 120,
        burst: int = 20,
        webhook_requests_per_minute: int = 600,
        webhook_burst: int = 60,
        auth_requests_per_minute: int = 10,
        auth_burst: int = 5,
        trusted_proxies: tuple[IPNetwork, ...] = (),
    ) -> None:
        super().__init__(app)
        self.requests_per_minute = max(requests_per_minute, 1)
        self.burst = max(burst, 1)
        self.webhook_requests_per_minute = max(webhook_requests_per_minute, 1)
        self.webhook_burst = max(webhook_burst, 1)
        self.auth_requests_per_minute = max(auth_requests_per_minute, 1)
        self.auth_burst = max(auth_burst, 1)
        self.trusted_proxies = trusted_proxies
        self._tokens: dict[str, float] = defaultdict(float)
        self._last_update: dict[str, float] = defaultdict(float)
        self._webhook_tokens: dict[str, float] = defaultdict(float)
        self._webhook_last_update: dict[str, float] = defaultdict(float)
        self._auth_tokens: dict[str, float] = defaultdict(float)
        self._auth_last_update: dict[str, float] = defaultdict(float)
        # Bounded LRU of token hashes verified by the auth dependency.
        self._authenticated: OrderedDict[str, None] = OrderedDict()
        self._lock: Any = None

    async def _get_lock(self) -> Any:
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        return self._lock

    def _is_trusted_proxy(self, host: str) -> bool:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(address in network for network in self.trusted_proxies)

    def client_ip(self, request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        if not self._is_trusted_proxy(peer):
            return peer
        hops = [
            hop.strip()
            for header in request.headers.getlist("x-forwarded-for")
            for hop in header.split(",")
            if hop.strip()
        ]
        for hop in reversed(hops):
            if not self._is_trusted_proxy(hop):
                return hop
        return hops[0] if hops else peer

    @staticmethod
    def _bearer_hash(request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return None
        token = auth[7:].strip()
        return hashlib.sha256(token.encode()).hexdigest()[:32] if token else None

    def _key(self, request: Request, token_hash: str | None) -> str:
        if token_hash is not None and token_hash in self._authenticated:
            self._authenticated.move_to_end(token_hash)
            return f"token:{token_hash}"
        return f"ip:{self.client_ip(request)}"

    def _record_auth_outcome(
        self, request: Request, token_hash: str | None, response: Response
    ) -> None:
        if token_hash is None:
            return
        if getattr(request.state, AUTHENTICATED_STATE_FLAG, False):
            self._authenticated[token_hash] = None
            self._authenticated.move_to_end(token_hash)
            while len(self._authenticated) > self.MAX_AUTHENTICATED_TOKENS:
                self._authenticated.popitem(last=False)
        elif response.status_code == 401:
            # Revoked since it was cached: back to the IP bucket.
            self._authenticated.pop(token_hash, None)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in {"/healthz", "/metrics"}:
            return await call_next(request)

        # The GitHub webhook has its own bucket (DEC-0059): it carries no
        # machine token, so the default per-token key would collapse every
        # GitHub retry onto one IP bucket and throttle legitimate
        # redeliveries. Keyed per repository event stream instead.
        if path == "/api/v1/github/webhook":
            return await self._dispatch_with_bucket(
                call_next,
                request,
                "github-webhook" + self._key(request, None),
                self._webhook_tokens,
                self._webhook_last_update,
                self.webhook_requests_per_minute,
                self.webhook_burst,
            )
        # Login and other auth endpoints: always per client IP, whatever the
        # bearer, with a stricter budget against credential stuffing.
        if path.startswith(self.AUTH_PATH_PREFIX) and path not in self.AUTHENTICATED_AUTH_PATHS:
            return await self._dispatch_with_bucket(
                call_next,
                request,
                "auth" + self._key(request, None),
                self._auth_tokens,
                self._auth_last_update,
                self.auth_requests_per_minute,
                self.auth_burst,
            )
        token_hash = self._bearer_hash(request)
        response = await self._dispatch_with_bucket(
            call_next,
            request,
            self._key(request, token_hash),
            self._tokens,
            self._last_update,
            self.requests_per_minute,
            self.burst,
        )
        self._record_auth_outcome(request, token_hash, response)
        return response

    async def _dispatch_with_bucket(
        self,
        call_next: RequestResponseEndpoint,
        request: Request,
        key: str,
        tokens: dict[str, float],
        last_update: dict[str, float],
        requests_per_minute: int,
        burst: int,
    ) -> Response:
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
            expose_headers=[settings.request_id_header],
        )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.rate_limit_requests_per_minute,
        burst=settings.rate_limit_burst,
        webhook_requests_per_minute=settings.github_webhook_rate_limit_per_minute,
        webhook_burst=settings.github_webhook_rate_limit_burst,
        auth_requests_per_minute=settings.auth_rate_limit_requests_per_minute,
        auth_burst=settings.auth_rate_limit_burst,
        trusted_proxies=parse_trusted_proxies(settings.trusted_proxies),
    )
    app.add_middleware(MetricsMiddleware)
