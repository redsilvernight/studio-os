"""Security event log (A1): auth outcomes are logged, secrets never are."""

from __future__ import annotations

import io
import json
import logging
import sys
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.observability import configure_logging
from studio_api.security_log import (
    REDACTED,
    SECURITY_EVENT_ATTR,
    RedactingFilter,
    email_digest,
    redact,
    security_event,
)
from studio_api.services import provisioning as provisioning_service

from tests.api.conftest import TEST_DATABASE_URL

_EMAIL = "sec-log@example.test"
_PASSWORD = "hunter2-very-secret"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXNpZ25hdHVyZQ"
_BCRYPT = "$2b$12$" + "a" * 53

needs_db = pytest.mark.skipif(TEST_DATABASE_URL is None, reason="no test database configured")


def _events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        getattr(r, SECURITY_EVENT_ATTR) for r in caplog.records if hasattr(r, SECURITY_EVENT_ATTR)
    ]


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("Authorization: Bearer sk_live_abcdef123456", "sk_live_abcdef123456"),
        (f"got token {_JWT}", _JWT),
        (f"password={_PASSWORD}&next=/", _PASSWORD),
        (json.dumps({"email": _EMAIL, "password": _PASSWORD}), _PASSWORD),
        ("STUDIO_JWT_SECRET=abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
        (f"stored hash {_BCRYPT}", _BCRYPT),
    ],
)
def test_redact_masks_credentials(raw: str, secret: str) -> None:
    redacted = redact(raw)
    assert secret not in redacted
    assert REDACTED in redacted


def test_redact_keeps_ordinary_text() -> None:
    text = "security event=auth.login outcome=failure reason=invalid_or_revoked"
    assert redact(text) == text


def test_filter_redacts_args_and_exceptions() -> None:
    try:
        raise ValueError(f"bad bearer Bearer {_JWT}")
    except ValueError:
        record = logging.LogRecord(
            "x", logging.ERROR, __file__, 1, "login %s", (f"password={_PASSWORD}",), sys.exc_info()
        )
    assert RedactingFilter().filter(record)
    assert _PASSWORD not in record.getMessage()
    assert record.exc_text is not None and _JWT not in record.exc_text


@pytest.fixture
def restore_root_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.usefixtures("restore_root_logging")
@pytest.mark.parametrize("log_format", ["text", "json"])
def test_configured_handlers_redact(log_format: str, monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    configure_logging(log_format, "INFO")

    logging.getLogger("anything").warning("leak %s", f"Bearer {_JWT}")
    security_event("auth.login", outcome="failure", email_digest=email_digest(_EMAIL))

    output = stream.getvalue()
    assert _JWT not in output
    assert "auth.login" in output
    if log_format == "json":
        last = json.loads(output.strip().splitlines()[-1])
        assert last[SECURITY_EVENT_ATTR]["event"] == "auth.login"


@needs_db
@pytest.mark.asyncio
async def test_login_outcomes_are_logged_without_secrets(
    client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    user = await provisioning_service.create_user(db_session, "Sec Log", _EMAIL, "developer")
    with caplog.at_level(logging.INFO, logger="studio.security"):
        await provisioning_service.set_user_password(db_session, _EMAIL, _PASSWORD)
        bad = await client.post(
            "/api/v1/auth/token", json={"email": _EMAIL, "password": "wrong-" + _PASSWORD}
        )
        good = await client.post(
            "/api/v1/auth/token", json={"email": _EMAIL, "password": _PASSWORD}
        )
    assert (bad.status_code, good.status_code) == (401, 200)

    events = _events(caplog)
    assert [(e["event"], e["outcome"]) for e in events] == [
        ("credential.password_set", "success"),
        ("auth.login", "failure"),
        ("auth.login", "success"),
    ]
    assert events[1]["email_digest"] == email_digest(_EMAIL)
    assert events[2]["user_id"] == str(user.id)
    assert "client_ip" in events[1]

    text = caplog.text
    for secret in (_PASSWORD, _EMAIL, good.json()["access_token"]):
        assert secret not in text


@needs_db
@pytest.mark.asyncio
async def test_rejected_bearer_is_logged_without_the_token(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    fake = "stm_fake_token_value_0123456789"
    with caplog.at_level(logging.INFO, logger="studio.security"):
        response = await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {fake}"})
    assert response.status_code == 401

    events = _events(caplog)
    assert [(e["event"], e["outcome"], e["path"]) for e in events] == [
        ("auth.bearer", "failure", "/api/v1/projects")
    ]
    assert fake not in caplog.text


@needs_db
@pytest.mark.asyncio
async def test_machine_revocation_is_logged(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    user = await provisioning_service.create_user(db_session, "Sec Rev", _EMAIL, "developer")
    machine, token = await provisioning_service.create_machine(db_session, user.id, "laptop")
    with caplog.at_level(logging.INFO, logger="studio.security"):
        await provisioning_service.revoke_machine(db_session, machine)
        await provisioning_service.revoke_machine(db_session, machine)  # idempotent: once

    events = _events(caplog)
    assert [(e["event"], e["machine_id"]) for e in events] == [
        ("credential.machine_revoked", str(machine.id))
    ]
    assert token not in caplog.text
