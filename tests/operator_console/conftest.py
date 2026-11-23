"""Tests of the separate operator console (fiches C0 to C5).

The console is its own application: these tests never touch the core API app,
never need PostgreSQL (the repository is replaced by an in-memory fake) and
pin the MFA gate, the aggregate shapes and the absence of any content route.
"""

from __future__ import annotations

import json
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Must happen before `studio_operator.main` is imported: it builds the app on
# import and refuses a weak secret in production (the default environment).
os.environ.setdefault("STUDIO_OPERATOR_ENVIRONMENT", "test")
os.environ.setdefault("STUDIO_OPERATOR_JWT_SECRET", "operator-test-secret-0123456789abcdef")
os.environ.setdefault("STUDIO_OPERATOR_OPERATORS", json.dumps([]))

from studio_operator.auth import (  # noqa: E402
    AttemptTracker,
    create_access_token,
    get_attempt_tracker,
)
from studio_operator.main import app  # noqa: E402
from studio_operator.repository import get_repository  # noqa: E402
from studio_operator.secrets_store import SecretStore, get_secret_store  # noqa: E402
from studio_operator.settings import (  # noqa: E402
    OperatorAccount,
    OperatorSettings,
    get_settings,
)

from tests.operator_console.fakes import FakeRepository  # noqa: E402

TOTP_SECRET = "JBSWY3DPEHPK3PXP"
EMAIL = "flo@example.test"
PASSWORD = "correct horse battery staple"
# bcrypt hash of PASSWORD at the cheapest work factor, for test speed only.
PASSWORD_HASH = "$2b$04$xvuOOX318uTpHCG6hO6jo.ztUTiGTEhDJzxJryKgcNvp845cQqG7m"
JWT_SECRET = "operator-test-secret-0123456789abcdef"


def operator_settings(**overrides: object) -> OperatorSettings:
    values: dict[str, object] = {
        "environment": "test",
        "jwt_secret": JWT_SECRET,
        "operators": [
            OperatorAccount(
                email=EMAIL,
                display_name="Flo Opérateur",
                password_hash=PASSWORD_HASH,
                totp_secret=TOTP_SECRET,
            ),
            # Listed, correct password, no MFA yet: must enroll through the QR.
            OperatorAccount(
                email="a-enroler@example.test",
                display_name="À enrôler",
                password_hash=PASSWORD_HASH,
            ),
            # Listed, MFA configured, no password: refused.
            OperatorAccount(
                email="sans-mdp@example.test",
                display_name="Sans mot de passe",
                totp_secret=TOTP_SECRET,
            ),
        ],
    }
    values.update(overrides)
    return OperatorSettings(**values)


@pytest.fixture
def settings() -> OperatorSettings:
    return operator_settings()


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def store(tmp_path) -> SecretStore:
    return SecretStore(tmp_path / "operator-secrets.json")


@pytest.fixture
def tracker(settings: OperatorSettings) -> AttemptTracker:
    return AttemptTracker(
        max_attempts=settings.mfa_max_attempts,
        lockout_seconds=settings.mfa_lockout_minutes * 60,
    )


@pytest_asyncio.fixture
async def client(
    settings: OperatorSettings,
    repository: FakeRepository,
    tracker: AttemptTracker,
    store: SecretStore,
):
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_attempt_tracker] = lambda: tracker
    app.dependency_overrides[get_secret_store] = lambda: store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://console.test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.fixture
def operator(settings: OperatorSettings) -> OperatorAccount:
    account = settings.operator(EMAIL)
    assert account is not None
    return account


@pytest.fixture
def auth_headers(operator: OperatorAccount, settings: OperatorSettings) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(operator, settings)}"}
