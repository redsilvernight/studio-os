"""Login must not reveal whether an email exists (A1, anti-enumeration)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.access_registry import HTTP_ACCESS
from studio_api.services import provisioning as provisioning_service

from tests.api.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="no test database configured",
)

_EMAIL = "anti-enum@example.test"
_NO_PASSWORD_EMAIL = "anti-enum-nopw@example.test"
_PASSWORD = "correct-horse-battery"


@pytest.fixture
def bcrypt_checks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records every bcrypt verification the login performs."""
    calls: list[str] = []
    real = provisioning_service._verify_password

    def _spy(password: str, password_hash: str) -> bool:
        calls.append(password_hash)
        return real(password, password_hash)

    monkeypatch.setattr(provisioning_service, "_verify_password", _spy)
    return calls


async def _login(client: AsyncClient, email: str, password: str) -> Any:
    return await client.post("/api/v1/auth/token", json={"email": email, "password": password})


@pytest.mark.asyncio
async def test_failed_logins_are_indistinguishable(
    client: AsyncClient, db_session: AsyncSession, bcrypt_checks: list[str]
) -> None:
    await provisioning_service.create_user(db_session, "Anti Enum", _EMAIL, "developer")
    await provisioning_service.set_user_password(db_session, _EMAIL, _PASSWORD)
    await provisioning_service.create_user(
        db_session, "No Password", _NO_PASSWORD_EMAIL, "developer"
    )

    responses = [
        await _login(client, _EMAIL, "wrong-password"),
        await _login(client, "unknown@example.test", "wrong-password"),
        await _login(client, _NO_PASSWORD_EMAIL, "wrong-password"),
    ]

    assert {r.status_code for r in responses} == {401}
    assert len({r.content for r in responses}) == 1
    # Each attempt pays exactly one bcrypt check, known email or not.
    assert len(bcrypt_checks) == 3
    assert bcrypt_checks[1] == bcrypt_checks[2] == provisioning_service._DUMMY_PASSWORD_HASH


@pytest.mark.asyncio
async def test_dummy_hash_never_authenticates(db_session: AsyncSession) -> None:
    await provisioning_service.create_user(
        db_session, "No Password", _NO_PASSWORD_EMAIL, "developer"
    )

    assert (
        await provisioning_service.verify_user_password(
            db_session, _NO_PASSWORD_EMAIL, "studio-os-dummy-password"
        )
        is None
    )


def test_dummy_hash_has_the_real_cost() -> None:
    real_cost = provisioning_service._hash_password("x").split("$")[2]
    assert provisioning_service._DUMMY_PASSWORD_HASH.split("$")[2] == real_cost


def test_no_public_route_can_reveal_a_duplicate() -> None:
    """Public writes are login and the signed webhook only: no unauthenticated
    creation route exists that could answer "already registered". A new public
    route (e.g. self-registration) must be reviewed for anti-enumeration and
    added here deliberately."""
    public_writes = {
        (method, path)
        for (method, path), access in HTTP_ACCESS.items()
        if access == "public" and method != "GET"
    }
    assert public_writes == {
        ("POST", "/api/v1/auth/token"),
        ("POST", "/api/v1/github/webhook"),
    }
