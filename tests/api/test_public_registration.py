"""Public registration and account recovery (A4, DU-0/A / DEC-0109): closed by
default, non-discriminating answers, hashed single-use secrets, required
Idempotency-Key, no privilege through public endpoints."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.account_token import AccountTokenModel, AccountTokenPurpose
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.user import UserModel
from studio_api.mailer import (
    FileEmailSender,
    OutgoingEmail,
    email_settings_problems,
    get_email_sender,
)
from studio_api.main import app
from studio_api.services import accounts as accounts_service
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import Settings, get_settings

pytestmark = pytest.mark.isolation

PASSWORD = "correct horse battery"
OTHER_PASSWORD = "another long password"
_TOKEN_RE = re.compile(r"#token=([A-Za-z0-9_-]+)")


class Outbox:
    enabled = True

    def __init__(self) -> None:
        self.messages: list[OutgoingEmail] = []

    async def send(self, message: OutgoingEmail) -> None:
        self.messages.append(message)

    def to(self, email: str) -> list[OutgoingEmail]:
        return [m for m in self.messages if m.to == email]

    def last_secret(self, email: str) -> str:
        match = _TOKEN_RE.search(self.to(email)[-1].body)
        assert match is not None
        return match.group(1)


class DisabledOutbox(Outbox):
    enabled = False


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "public_registration_enabled": True,
        "email_backend": "file",
        "email_from": "studio@example.test",
        "account_email_cooldown_seconds": 0,
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
def open_instance(outbox: Outbox) -> Iterator[Settings]:
    settings = _settings()
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


@pytest_asyncio.fixture
async def active_user(db_session: AsyncSession) -> AsyncIterator[UserModel]:
    user = await provisioning_service.create_user(
        db_session, "Active", f"{uuid.uuid4()}@example.test", "developer"
    )
    yield await provisioning_service.set_user_password(db_session, user.email, PASSWORD)


def _email() -> str:
    return f"{uuid.uuid4()}@example.test"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def _register(
    client: AsyncClient, email: str, password: str = PASSWORD, **extra: object
) -> tuple[int, dict[str, object]]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "Ada", **extra},
        headers=_key(),
    )
    return response.status_code, response.json()


async def _login(client: AsyncClient, email: str, password: str) -> int:
    response = await client.post("/api/v1/auth/token", json={"email": email, "password": password})
    return response.status_code


async def _jwt(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/token", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --- Flag -------------------------------------------------------------------


async def test_closed_by_default_every_registration_route_is_unavailable(
    client: AsyncClient, outbox: Outbox, active_user: UserModel
) -> None:
    assert Settings().public_registration_enabled is False
    for path, body in (
        ("/api/v1/auth/register", {"email": _email(), "password": PASSWORD, "display_name": "A"}),
        ("/api/v1/auth/resend-verification", {"email": active_user.email}),
        ("/api/v1/auth/verify-email", {"token": "x" * 43}),
    ):
        response = await client.post(path, json=body, headers=_key())
        assert response.status_code == 404, path
        assert response.json() == {"detail": {"error_code": "registration_unavailable"}}
    assert outbox.messages == []
    assert await _login(client, active_user.email, PASSWORD) == 200


async def test_recovery_needs_an_email_backend(client: AsyncClient, active_user: UserModel) -> None:
    app.dependency_overrides[get_email_sender] = DisabledOutbox
    try:
        for path, body in (
            ("/api/v1/auth/forgot-password", {"email": active_user.email}),
            ("/api/v1/auth/reset-password", {"token": "x" * 43, "new_password": OTHER_PASSWORD}),
        ):
            response = await client.post(path, json=body, headers=_key())
            assert response.status_code == 404, path
            assert response.json() == {"detail": {"error_code": "password_recovery_unavailable"}}
    finally:
        app.dependency_overrides.pop(get_email_sender, None)


def test_startup_refuses_inconsistent_email_settings() -> None:
    assert email_settings_problems(Settings()) == []
    assert email_settings_problems(_settings()) == []
    assert email_settings_problems(_settings(email_backend="disabled"))
    assert email_settings_problems(_settings(email_from=None))
    assert email_settings_problems(_settings(email_backend="smtp", smtp_host=None))
    assert email_settings_problems(
        _settings(email_backend="smtp", smtp_host="smtp.example.test", smtp_username="u")
    )
    assert email_settings_problems(_settings(environment="production"))
    assert email_settings_problems(
        _settings(
            environment="production",
            email_backend="smtp",
            smtp_host="smtp.example.test",
            public_base_url="http://studio.example.test",
        )
    )
    assert (
        email_settings_problems(
            _settings(
                environment="production",
                email_backend="smtp",
                smtp_host="smtp.example.test",
                public_base_url="https://studio.example.test",
            )
        )
        == []
    )


# --- Registration and verification ------------------------------------------


async def test_register_verify_then_login(
    client: AsyncClient, db_session: AsyncSession, open_instance: Settings, outbox: Outbox
) -> None:
    email = _email()
    assert await _register(client, email) == (202, {"status": "accepted"})

    user = await provisioning_service.get_user_by_email(db_session, email)
    assert user is not None
    assert (user.role, user.status, user.password_hash) == ("readonly", "pending", None)
    assert await _login(client, email, PASSWORD) == 401

    secret = outbox.last_secret(email)
    assert "/verify-email#token=" in outbox.to(email)[0].body
    verified = await client.post("/api/v1/auth/verify-email", json={"token": secret})
    assert verified.status_code == 200, verified.text
    assert verified.json() == {"status": "verified"}
    assert await _login(client, email, PASSWORD) == 200

    replay = await client.post("/api/v1/auth/verify-email", json={"token": secret})
    assert (replay.status_code, replay.json()) == (200, {"status": "verified"})

    unknown = await client.post("/api/v1/auth/verify-email", json={"token": "y" * 43})
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["error_code"] == "invalid_or_expired_token"


async def test_self_registered_account_gets_no_privilege_by_field_injection(
    client: AsyncClient, db_session: AsyncSession, open_instance: Settings, outbox: Outbox
) -> None:
    email = _email()
    status_code, _ = await _register(
        client,
        email,
        role="admin",
        status="active",
        email_verified_at="2026-01-01T00:00:00Z",
        disabled_at=None,
        auth_version=99,
        project_id=str(uuid.uuid4()),
        memberships=[{"project_id": str(uuid.uuid4()), "role": "developer"}],
        id=str(uuid.uuid4()),
    )
    assert status_code == 202
    user = await provisioning_service.get_user_by_email(db_session, email)
    assert user is not None
    assert (user.role, user.status, user.auth_version) == ("readonly", "pending", 0)
    await client.post("/api/v1/auth/verify-email", json={"token": outbox.last_secret(email)})
    await db_session.refresh(user)
    assert (user.role, user.status) == ("readonly", "active")
    memberships = await db_session.execute(
        select(func.count())
        .select_from(ProjectMembershipModel)
        .where(ProjectMembershipModel.user_id == user.id)
    )
    assert memberships.scalar_one() == 0
    headers = await _jwt(client, email, PASSWORD)
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["role"] == "readonly"
    denied = await client.post(
        "/api/v1/users",
        json={"display_name": "X", "email": _email(), "role": "admin"},
        headers=headers,
    )
    assert denied.status_code == 403


async def test_register_answers_the_same_for_existing_and_new_addresses(
    client: AsyncClient,
    db_session: AsyncSession,
    open_instance: Settings,
    outbox: Outbox,
    active_user: UserModel,
) -> None:
    new = await _register(client, _email())
    existing = await _register(client, active_user.email.upper(), OTHER_PASSWORD)
    assert new == existing == (202, {"status": "accepted"})
    assert outbox.to(active_user.email) == []
    await db_session.refresh(active_user)
    assert provisioning_service.check_password(PASSWORD, active_user.password_hash or "")


async def test_resend_only_reaches_pending_accounts(
    client: AsyncClient, open_instance: Settings, outbox: Outbox, active_user: UserModel
) -> None:
    email = _email()
    await _register(client, email)
    first = outbox.last_secret(email)
    responses = []
    for address in (email, active_user.email, _email()):
        response = await client.post(
            "/api/v1/auth/resend-verification", json={"email": address}, headers=_key()
        )
        responses.append((response.status_code, response.json()))
    assert responses == [(202, {"status": "accepted"})] * 3
    assert len(outbox.to(email)) == 2
    assert outbox.to(active_user.email) == []

    stale = await client.post("/api/v1/auth/verify-email", json={"token": first})
    assert stale.status_code == 400
    fresh = await client.post(
        "/api/v1/auth/verify-email", json={"token": outbox.last_secret(email)}
    )
    assert fresh.status_code == 200
    assert await _login(client, email, PASSWORD) == 200


async def test_the_owner_link_sets_the_owner_password(
    client: AsyncClient, open_instance: Settings, outbox: Outbox
) -> None:
    email = _email()
    await _register(client, email, "stranger password!!")
    stranger_link = outbox.last_secret(email)
    await _register(client, email, PASSWORD)
    owner_link = outbox.last_secret(email)

    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": stranger_link})
    ).status_code == 400
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": owner_link})
    ).status_code == 200
    assert await _login(client, email, "stranger password!!") == 401
    assert await _login(client, email, PASSWORD) == 200


async def test_cooldown_silently_limits_repeated_emails(
    client: AsyncClient, outbox: Outbox, open_instance: Settings
) -> None:
    settings = _settings(account_email_cooldown_seconds=3600)
    app.dependency_overrides[get_settings] = lambda: settings
    email = _email()
    await _register(client, email)
    response = await client.post(
        "/api/v1/auth/resend-verification", json={"email": email}, headers=_key()
    )
    assert (response.status_code, response.json()) == (202, {"status": "accepted"})
    assert len(outbox.to(email)) == 1


# --- Idempotency ------------------------------------------------------------


async def test_register_resend_forgot_require_an_idempotency_key(
    client: AsyncClient, open_instance: Settings, active_user: UserModel
) -> None:
    for path, body in (
        ("/api/v1/auth/register", {"email": _email(), "password": PASSWORD, "display_name": "A"}),
        ("/api/v1/auth/resend-verification", {"email": _email()}),
        ("/api/v1/auth/forgot-password", {"email": active_user.email}),
    ):
        response = await client.post(path, json=body)
        assert response.status_code == 400, path
        assert response.json() == {"detail": {"error_code": "idempotency_key_required"}}


async def test_register_replay_creates_nothing_more(
    client: AsyncClient, db_session: AsyncSession, open_instance: Settings, outbox: Outbox
) -> None:
    email = _email()
    headers = _key()
    body = {"email": email, "password": PASSWORD, "display_name": "Ada"}
    first = await client.post("/api/v1/auth/register", json=body, headers=headers)
    replay = await client.post("/api/v1/auth/register", json=body, headers=headers)
    assert (first.status_code, first.json()) == (replay.status_code, replay.json())
    assert len(outbox.to(email)) == 1
    tokens = await db_session.execute(
        select(func.count())
        .select_from(AccountTokenModel)
        .join(UserModel, UserModel.id == AccountTokenModel.user_id)
        .where(UserModel.email == email)
    )
    assert tokens.scalar_one() == 1

    mismatch = await client.post(
        "/api/v1/auth/register", json={**body, "display_name": "Eve"}, headers=headers
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"


# --- Secrets ----------------------------------------------------------------


async def test_secrets_are_hashed_single_use_expiring_and_never_logged(
    client: AsyncClient,
    db_session: AsyncSession,
    open_instance: Settings,
    outbox: Outbox,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    email = _email()
    await _register(client, email)
    secret = outbox.last_secret(email)
    assert len(secret) >= 43

    rows = (
        (
            await db_session.execute(
                select(AccountTokenModel)
                .join(UserModel, UserModel.id == AccountTokenModel.user_id)
                .where(UserModel.email == email)
            )
        )
        .scalars()
        .all()
    )
    assert [row.token_hash for row in rows] == [hashlib.sha256(secret.encode()).hexdigest()]
    assert rows[0].purpose == AccountTokenPurpose.EMAIL_VERIFICATION

    await db_session.execute(
        update(AccountTokenModel)
        .where(AccountTokenModel.id == rows[0].id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    expired = await client.post("/api/v1/auth/verify-email", json={"token": secret})
    assert expired.status_code == 400

    await client.post("/api/v1/auth/resend-verification", json={"email": email}, headers=_key())
    fresh = outbox.last_secret(email)
    assert (
        await accounts_service._consume(db_session, fresh, AccountTokenPurpose.EMAIL_VERIFICATION)
        is not None
    )
    assert (
        await accounts_service._consume(db_session, fresh, AccountTokenPurpose.EMAIL_VERIFICATION)
        is None
    )
    assert (
        await accounts_service._consume(db_session, fresh, AccountTokenPurpose.PASSWORD_RESET)
        is None
    )

    for value in (secret, fresh, PASSWORD):
        assert value not in caplog.text


# --- Recovery ---------------------------------------------------------------


async def test_forgot_answers_the_same_and_skips_disabled_accounts(
    client: AsyncClient,
    db_session: AsyncSession,
    open_instance: Settings,
    outbox: Outbox,
    active_user: UserModel,
) -> None:
    disabled = await provisioning_service.create_user(db_session, "Disabled", _email(), "developer")
    await provisioning_service.disable_account(db_session, disabled)
    answers = []
    for address in (active_user.email, _email(), disabled.email):
        response = await client.post(
            "/api/v1/auth/forgot-password", json={"email": address}, headers=_key()
        )
        answers.append((response.status_code, response.json()))
    assert answers == [(202, {"status": "accepted"})] * 3
    assert len(outbox.to(active_user.email)) == 1
    assert outbox.to(disabled.email) == []


async def test_forgot_works_with_registration_closed(
    client: AsyncClient, outbox: Outbox, active_user: UserModel
) -> None:
    response = await client.post(
        "/api/v1/auth/forgot-password", json={"email": active_user.email}, headers=_key()
    )
    assert response.status_code == 202
    assert len(outbox.to(active_user.email)) == 1


async def test_reset_password_revokes_sessions_and_replays(
    client: AsyncClient, open_instance: Settings, outbox: Outbox, active_user: UserModel
) -> None:
    old_jwt = await _jwt(client, active_user.email, PASSWORD)
    await client.post(
        "/api/v1/auth/forgot-password", json={"email": active_user.email}, headers=_key()
    )
    secret = outbox.last_secret(active_user.email)
    assert "/reset-password#token=" in outbox.to(active_user.email)[-1].body
    body = {"token": secret, "new_password": OTHER_PASSWORD}

    reset = await client.post("/api/v1/auth/reset-password", json=body)
    assert (reset.status_code, reset.json()) == (200, {"status": "password_reset"})
    assert (await client.get("/api/v1/auth/me", headers=old_jwt)).status_code == 401
    assert await _login(client, active_user.email, PASSWORD) == 401
    assert await _login(client, active_user.email, OTHER_PASSWORD) == 200

    replay = await client.post("/api/v1/auth/reset-password", json=body)
    assert (replay.status_code, replay.json()) == (200, {"status": "password_reset"})
    other = await client.post(
        "/api/v1/auth/reset-password", json={"token": secret, "new_password": "third password!!"}
    )
    assert other.status_code == 409
    assert await _login(client, active_user.email, OTHER_PASSWORD) == 200


async def test_reset_verifies_a_pending_account(
    client: AsyncClient, open_instance: Settings, outbox: Outbox
) -> None:
    email = _email()
    await _register(client, email)
    await client.post("/api/v1/auth/forgot-password", json={"email": email}, headers=_key())
    reset = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": outbox.last_secret(email), "new_password": OTHER_PASSWORD},
    )
    assert reset.status_code == 200
    assert await _login(client, email, OTHER_PASSWORD) == 200


async def test_new_passwords_follow_the_policy(
    client: AsyncClient, open_instance: Settings
) -> None:
    for password in ("short", "é" * 37):
        status_code, _ = await _register(client, _email(), password)
        assert status_code == 422


async def test_change_password_requires_the_current_one_and_revokes_sessions(
    client: AsyncClient, active_user: UserModel
) -> None:
    headers = await _jwt(client, active_user.email, PASSWORD)
    wrong = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not the password", "new_password": OTHER_PASSWORD},
        headers=headers,
    )
    assert wrong.status_code == 400
    assert wrong.json()["detail"]["error_code"] == "invalid_current_password"

    changed = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": OTHER_PASSWORD},
        headers=headers,
    )
    assert (changed.status_code, changed.json()) == (200, {"status": "password_changed"})
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    assert await _login(client, active_user.email, OTHER_PASSWORD) == 200


async def test_change_password_needs_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": OTHER_PASSWORD},
    )
    assert response.status_code == 401


# --- Mailer -----------------------------------------------------------------


async def test_file_backend_writes_eml(tmp_path: Path) -> None:
    sender = FileEmailSender(str(tmp_path), "studio@example.test")
    await sender.send(OutgoingEmail("ada@example.test", "Sujet", "Corps", "email_verification"))
    files = list(tmp_path.glob("*-email_verification-*.eml"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "To: ada@example.test" in content and "Corps" in content
