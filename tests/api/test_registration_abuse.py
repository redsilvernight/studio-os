"""Anti-abuse on public self-registration (S5): per-IP and per-domain quotas,
configurable disposable domains, bot-protection hook disabled by default.

Counters are in memory per process and keyed by their limits profile, so each
test gets a fresh `RegistrationGuard` through the dependency override.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.user import UserModel
from studio_api.mailer import OutgoingEmail, get_email_sender
from studio_api.main import app
from studio_api.registration_guard import (
    RegistrationGuard,
    get_registration_guard,
)
from studio_api.settings import Settings, get_settings

pytestmark = pytest.mark.isolation


class Outbox:
    enabled = True

    def __init__(self) -> None:
        self.messages: list[OutgoingEmail] = []

    async def send(self, message: OutgoingEmail) -> None:
        self.messages.append(message)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "public_registration_enabled": True,
        "email_backend": "file",
        "email_from": "studio@example.test",
        "account_email_cooldown_seconds": 0,
        "registration_ip_limit": 0,
        "registration_domain_limit": 0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def outbox() -> Iterator[Outbox]:
    box = Outbox()
    app.dependency_overrides[get_email_sender] = lambda: box
    yield box
    app.dependency_overrides.pop(get_email_sender, None)


@pytest.fixture
def guard() -> Iterator[RegistrationGuard]:
    fresh = RegistrationGuard()
    app.dependency_overrides[get_registration_guard] = lambda: fresh
    yield fresh
    app.dependency_overrides.pop(get_registration_guard, None)


@pytest.fixture
def settings(outbox: Outbox, guard: RegistrationGuard) -> Iterator[Settings]:
    current = _settings()
    app.dependency_overrides[get_settings] = lambda: current
    yield current
    app.dependency_overrides.pop(get_settings, None)


def _configure(current: Settings, **overrides: object) -> Settings:
    updated = _settings(**overrides)
    app.dependency_overrides[get_settings] = lambda: updated
    return updated


def _email(domain: str = "example.test") -> str:
    return f"{uuid.uuid4()}@{domain}"


async def _register(client: AsyncClient, email: str) -> tuple[int, dict[str, object]]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    return response.status_code, response.json()


async def _count_users(session: AsyncSession, email: str) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(UserModel).where(UserModel.email == email)
        )
    ).scalar_one()


async def test_ip_quota_blocks_a_second_registration(
    client: AsyncClient, settings: Settings, db_session: AsyncSession
) -> None:
    _configure(settings, registration_ip_limit=1)

    first = _email("first.test")
    assert await _register(client, first) == (202, {"status": "accepted"})

    blocked = _email("second.test")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": blocked},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 429
    assert response.json() == {
        "detail": {"error_code": "registration_rate_limited", "scope": "ip"}
    }
    assert int(response.headers["retry-after"]) >= 1
    assert await _count_users(db_session, blocked) == 0


async def test_domain_quota_is_shared_by_distinct_addresses(
    client: AsyncClient, settings: Settings
) -> None:
    _configure(settings, registration_domain_limit=1)

    assert await _register(client, _email("shared.test")) == (202, {"status": "accepted"})
    status_code, body = await _register(client, _email("shared.test"))
    assert status_code == 429
    assert body == {"detail": {"error_code": "registration_rate_limited", "scope": "domain"}}


async def test_disabled_quotas_do_not_block(
    client: AsyncClient, settings: Settings
) -> None:
    _configure(settings, registration_ip_limit=0, registration_domain_limit=0)
    for _ in range(3):
        assert await _register(client, _email()) == (202, {"status": "accepted"})


async def test_disposable_domain_is_rejected(
    client: AsyncClient, settings: Settings, db_session: AsyncSession, outbox: Outbox
) -> None:
    email = _email("mailinator.com")
    status_code, body = await _register(client, email)
    assert status_code == 400
    assert body == {"detail": {"error_code": "email_domain_not_allowed"}}
    assert await _count_users(db_session, email) == 0
    assert outbox.messages == []


async def test_subdomain_of_a_disposable_domain_is_rejected(
    client: AsyncClient, settings: Settings
) -> None:
    status_code, body = await _register(client, _email("sub.mailinator.com"))
    assert status_code == 400
    assert body == {"detail": {"error_code": "email_domain_not_allowed"}}


async def test_disposable_list_is_configurable(
    client: AsyncClient, settings: Settings
) -> None:
    # Replaces the built-in list: spam.test is blocked, mailinator.com is not.
    _configure(settings, registration_disposable_email_domains="spam.test")

    status_code, body = await _register(client, _email("spam.test"))
    assert status_code == 400
    assert body == {"detail": {"error_code": "email_domain_not_allowed"}}
    assert await _register(client, _email("mailinator.com")) == (202, {"status": "accepted"})


async def test_invalid_disposable_domain_setting_fails_fast() -> None:
    with pytest.raises(ValueError):
        _settings(registration_disposable_email_domains="not a domain")


async def test_bot_protection_is_off_by_default(
    client: AsyncClient, settings: Settings
) -> None:
    assert settings.registration_bot_protection_enabled is False
    assert await _register(client, _email()) == (202, {"status": "accepted"})


async def test_enabled_bot_protection_without_provider_fails_closed(
    client: AsyncClient, settings: Settings
) -> None:
    _configure(settings, registration_bot_protection_enabled=True)
    status_code, body = await _register(client, _email())
    assert status_code == 503
    assert body == {"detail": {"error_code": "registration_bot_protection_unavailable"}}

