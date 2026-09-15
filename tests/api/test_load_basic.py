"""Lightweight load/chaos test against the in-memory ASGI app.

Requires a real Postgres database (same rule as tests/api). This is not a
benchmark; it verifies the API stays stable under a small burst and that the
rate limiter does not starve legitimate traffic.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_burst(client: AsyncClient) -> None:
    """50 concurrent health checks must all succeed."""

    async def one() -> int:
        r = await client.get("/healthz")
        return r.status_code

    results = await asyncio.gather(*(one() for _ in range(50)))
    assert all(s == 200 for s in results)


@pytest.mark.asyncio
async def test_unauthenticated_burst(client: AsyncClient) -> None:
    """100 concurrent unauthenticated requests must be rejected, not crash."""

    async def one() -> int:
        r = await client.get("/api/v1/projects")
        return r.status_code

    results = await asyncio.gather(*(one() for _ in range(100)))
    assert all(s in {401, 429} for s in results)


@pytest.mark.asyncio
async def test_metrics_reflect_load(client: AsyncClient) -> None:
    await client.get("/healthz")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "studio_api_http_requests_total" in response.text
    assert 'method="GET"' in response.text
