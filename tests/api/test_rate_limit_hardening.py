"""A1 rate-limit hardening: trusted proxies, unverified bearers, /auth/* bucket."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.session import get_session
from studio_api.deps import CurrentMachine
from studio_api.middleware import setup_middleware
from studio_api.settings import Settings

# ASGITransport's default peer address.
_PEER = "127.0.0.1"


def _app(settings: Settings) -> FastAPI:
    app = FastAPI()
    setup_middleware(app, settings)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"ok": "ok"}

    @app.post("/api/v1/auth/token")
    def login() -> dict[str, str]:
        return {"ok": "ok"}

    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_spoofed_forwarded_for_from_untrusted_peer_is_ignored() -> None:
    app = _app(Settings(rate_limit_requests_per_minute=60, rate_limit_burst=3))

    async with _client(app) as ac:
        for i in range(3):
            response = await ac.get("/ok", headers={"x-forwarded-for": f"203.0.113.{i}"})
            assert response.status_code == 200
        response = await ac.get("/ok", headers={"x-forwarded-for": "203.0.113.99"})
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_trusted_proxy_keys_on_rightmost_untrusted_hop() -> None:
    app = _app(
        Settings(
            rate_limit_requests_per_minute=60,
            rate_limit_burst=2,
            trusted_proxies=f"{_PEER}/32, 10.0.0.0/8",
        )
    )

    async with _client(app) as ac:
        for _ in range(2):
            assert (
                await ac.get("/ok", headers={"x-forwarded-for": "198.51.100.7"})
            ).status_code == 200
        # A client-forged left part does not open a new bucket: the proxy
        # appended the real address on the right (10.x is a trusted hop).
        spoofed = await ac.get(
            "/ok", headers={"x-forwarded-for": "1.1.1.1, 198.51.100.7, 10.0.0.5"}
        )
        assert spoofed.status_code == 429
        # Another real client behind the same proxy has its own bucket.
        other = await ac.get("/ok", headers={"x-forwarded-for": "198.51.100.8"})
        assert other.status_code == 200


@pytest.mark.asyncio
async def test_auth_routes_have_a_stricter_ip_bucket() -> None:
    app = _app(
        Settings(
            rate_limit_requests_per_minute=60,
            rate_limit_burst=20,
            auth_rate_limit_requests_per_minute=60,
            auth_rate_limit_burst=2,
        )
    )

    async with _client(app) as ac:
        for i in range(2):
            headers = {"authorization": f"Bearer fake-{i}"}
            assert (await ac.post("/api/v1/auth/token", headers=headers)).status_code == 200
        rotated = await ac.post("/api/v1/auth/token", headers={"authorization": "Bearer fake-new"})
        assert rotated.status_code == 429
        assert (await ac.get("/ok")).status_code == 200


@pytest.fixture
def machine_app(db_session: AsyncSession) -> FastAPI:
    app = _app(Settings(rate_limit_requests_per_minute=60, rate_limit_burst=3))

    @app.get("/me")
    def me(machine: CurrentMachine) -> dict[str, str]:
        return {"id": str(machine.id)}

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    return app


@pytest.mark.asyncio
async def test_rotating_fake_bearers_does_not_bypass_the_limit(machine_app: FastAPI) -> None:
    async with _client(machine_app) as ac:
        for _ in range(3):
            headers = {"authorization": f"Bearer {uuid.uuid4().hex}"}
            assert (await ac.get("/me", headers=headers)).status_code == 401
        headers = {"authorization": f"Bearer {uuid.uuid4().hex}"}
        assert (await ac.get("/me", headers=headers)).status_code == 429


@pytest.mark.asyncio
async def test_verified_bearer_gets_its_own_bucket(
    machine_app: FastAPI, machine: tuple[MachineModel, str]
) -> None:
    _, token = machine
    headers = {"authorization": f"Bearer {token}"}

    async with _client(machine_app) as ac:
        # First use is charged to the IP; once verified, the token has its own bucket.
        assert (await ac.get("/me", headers=headers)).status_code == 200
        for _ in range(2):
            assert (await ac.get("/ok")).status_code == 200
        assert (await ac.get("/ok")).status_code == 429  # IP bucket empty
        for _ in range(3):
            assert (await ac.get("/me", headers=headers)).status_code == 200
        assert (await ac.get("/me", headers=headers)).status_code == 429
