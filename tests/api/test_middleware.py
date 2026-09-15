from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from studio_api.middleware import setup_middleware
from studio_api.settings import Settings


@pytest.mark.asyncio
async def test_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 32


@pytest.mark.asyncio
async def test_request_id_can_be_propagated() -> None:
    app = FastAPI()
    setup_middleware(app, Settings())

    @app.get("/echo")
    def echo() -> dict[str, str]:
        return {"ok": "ok"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/echo", headers={"x-request-id": "my-id-123"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "my-id-123"


@pytest.mark.asyncio
async def test_security_headers(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "usb=()" in response.headers.get("permissions-policy", "")


@pytest.mark.asyncio
async def test_rate_limit_by_ip() -> None:
    app = FastAPI()
    setup_middleware(app, Settings(rate_limit_requests_per_minute=60, rate_limit_burst=3))

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"ok": "ok"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for _ in range(3):
            response = await ac.get("/ok")
            assert response.status_code == 200
        response = await ac.get("/ok")
        assert response.status_code == 429
        assert response.json()["detail"] == "rate limit exceeded"


@pytest.mark.asyncio
async def test_rate_limit_skips_health_and_metrics() -> None:
    app = FastAPI()
    setup_middleware(app, Settings(rate_limit_requests_per_minute=60, rate_limit_burst=1))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics() -> dict[str, str]:
        return {"metrics": "ok"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for _ in range(5):
            assert (await ac.get("/healthz")).status_code == 200
            assert (await ac.get("/metrics")).status_code == 200


@pytest.mark.asyncio
async def test_cors_configured() -> None:
    app = FastAPI()
    setup_middleware(app, Settings(cors_origins="https://studio.example.com"))

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"ok": "ok"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.options(
            "/ok",
            headers={
                "origin": "https://studio.example.com",
                "access-control-request-method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "https://studio.example.com"
        assert "GET" in (response.headers.get("access-control-allow-methods") or "")


@pytest.mark.asyncio
async def test_cors_not_configured_by_default(client: AsyncClient) -> None:
    response = await client.get("/healthz", headers={"origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_metrics_endpoint(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "studio_api_http_requests_total" in response.text
