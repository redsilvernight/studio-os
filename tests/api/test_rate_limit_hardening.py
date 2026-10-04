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


def _limit_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = [
        r.__dict__["security_event"] for r in caplog.records if r.name == "studio.security"
    ]
    return [p for p in payloads if p["event"] == "rate_limit.exceeded"]


@pytest.mark.asyncio
async def test_429_emits_security_event_with_bucket_ip_and_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(
        Settings(
            rate_limit_requests_per_minute=60,
            rate_limit_burst=1,
            trusted_proxies=f"{_PEER}/32",
        )
    )
    caplog.set_level("INFO", logger="studio.security")

    async with _client(app) as ac:
        headers = {"x-forwarded-for": "198.51.100.7", "authorization": "Bearer s3cr3t-token-value"}
        assert (await ac.get("/ok", headers=headers)).status_code == 200
        assert (await ac.get("/ok?token=s3cr3t-query-value", headers=headers)).status_code == 429

    (event,) = _limit_events(caplog)
    assert event["outcome"] == "blocked"
    assert event["bucket"] == "general"
    assert event["client_ip"] == "198.51.100.7"  # resolved via trusted proxy, not the peer
    assert event["path"] == "/ok"
    rendered = " ".join(r.getMessage() for r in caplog.records) + str(event)
    assert "s3cr3t" not in rendered


@pytest.mark.asyncio
async def test_429_event_names_auth_bucket(caplog: pytest.LogCaptureFixture) -> None:
    app = _app(Settings(auth_rate_limit_requests_per_minute=60, auth_rate_limit_burst=1))
    caplog.set_level("INFO", logger="studio.security")

    async with _client(app) as ac:
        await ac.post("/api/v1/auth/token")
        assert (await ac.post("/api/v1/auth/token")).status_code == 429

    (event,) = _limit_events(caplog)
    assert event["bucket"] == "auth"
    assert event["client_ip"] == _PEER
    assert event["path"] == "/api/v1/auth/token"


@pytest.mark.asyncio
async def test_429_flood_logs_one_event_per_key_and_window(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr("studio_api.middleware.time.monotonic", lambda: now[0])
    app = _app(Settings(rate_limit_requests_per_minute=1, rate_limit_burst=1))
    caplog.set_level("INFO", logger="studio.security")

    async with _client(app) as ac:
        assert (await ac.get("/ok")).status_code == 200
        for _ in range(5):
            assert (await ac.get("/ok")).status_code == 429
        assert len(_limit_events(caplog)) == 1

        # Next window: one more event, reporting what was suppressed.
        now[0] += 61.0
        assert (await ac.get("/ok")).status_code == 200
        for _ in range(2):
            assert (await ac.get("/ok")).status_code == 429
    events = _limit_events(caplog)
    assert len(events) == 2
    assert events[1]["suppressed"] == "4"
