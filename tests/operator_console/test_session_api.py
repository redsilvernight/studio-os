from __future__ import annotations

from httpx import AsyncClient
from studio_operator.auth import OperatorAccount, create_access_token
from studio_operator.mfa import totp
from studio_operator.secrets_store import SecretStore
from studio_operator.settings import OperatorSettings

from tests.operator_console.conftest import EMAIL, PASSWORD, TOTP_SECRET

ENROLL_EMAIL = "a-enroler@example.test"


def _code(secret: str = TOTP_SECRET) -> str:
    return totp(secret)


def _login(email: str = EMAIL, password: str = PASSWORD, code: str | None = None):
    return {"email": email, "password": password, "code": _code() if code is None else code}


async def test_login_requires_email_password_and_mfa_code(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/mfa", json=_login())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert body["operator"] == {"email": EMAIL, "display_name": "Flo Opérateur"}
    assert response.headers["cache-control"] == "no-store"

    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL


async def test_email_is_matched_case_insensitively(client: AsyncClient) -> None:
    payload = _login(email="  FLO@Example.TEST ")
    assert (await client.post("/api/v1/auth/mfa", json=payload)).status_code == 200


async def test_a_wrong_password_gets_the_generic_refusal(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/mfa", json=_login(password="not-the-password"))

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "operator_not_allowed"


async def test_an_unknown_operator_gets_the_same_generic_refusal(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/mfa", json=_login(email="inconnu@example.test"))

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "operator_not_allowed"


async def test_a_listed_operator_without_password_hash_is_refused(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/mfa", json=_login(email="sans-mdp@example.test"))

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "operator_not_allowed"


async def test_a_manually_configured_secret_works_without_enrollment(
    client: AsyncClient,
) -> None:
    assert (await client.post("/api/v1/auth/mfa", json=_login())).status_code == 200


async def test_wrong_codes_count_down_then_lock_the_account(client: AsyncClient) -> None:
    for remaining in (2, 1):
        response = await client.post("/api/v1/auth/mfa", json=_login(code="000000"))
        assert response.status_code == 401
        detail = response.json()["detail"]
        assert detail["error_code"] == "mfa_invalid"
        assert detail["attempts_remaining"] == remaining

    locked = await client.post("/api/v1/auth/mfa", json=_login(code="000000"))
    assert locked.status_code == 429
    assert locked.json()["detail"]["error_code"] == "mfa_locked"
    assert int(locked.headers["retry-after"]) > 0

    still_locked = await client.post("/api/v1/auth/mfa", json=_login())
    assert still_locked.status_code == 429


async def test_wrong_passwords_also_lock_the_account(client: AsyncClient) -> None:
    for _ in range(2):
        response = await client.post("/api/v1/auth/mfa", json=_login(password="wrong-password"))
        assert response.status_code == 403

    locked = await client.post("/api/v1/auth/mfa", json=_login(password="wrong-password"))
    assert locked.status_code == 429
    assert locked.json()["detail"]["error_code"] == "mfa_locked"

    still_locked = await client.post("/api/v1/auth/mfa", json=_login())
    assert still_locked.status_code == 429


async def test_a_successful_login_resets_the_failed_attempts(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/mfa", json=_login(password="wrong-password"))
    assert (await client.post("/api/v1/auth/mfa", json=_login())).status_code == 200

    again = await client.post("/api/v1/auth/mfa", json=_login(code="000000"))
    assert again.status_code == 401
    assert again.json()["detail"]["attempts_remaining"] == 2


# -- enrollment (fiche C0, "Vide · première connexion") ---------------------


async def test_enrollment_requires_the_account_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/enrollment",
        json={"email": ENROLL_EMAIL, "password": "wrong-password"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "operator_not_allowed"


async def test_enrollment_refuses_an_account_whose_mfa_is_already_active(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/auth/enrollment", json={"email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "mfa_already_active"


async def test_enrollment_returns_otpauth_uri_and_qr_then_activates(
    client: AsyncClient, store: SecretStore
) -> None:
    started = await client.post(
        "/api/v1/auth/enrollment", json={"email": ENROLL_EMAIL, "password": PASSWORD}
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert "secret=" in body["otpauth_uri"]
    assert body["secret"] in body["otpauth_uri"]
    assert body["qr_svg"].startswith("<svg")
    assert body["expires_in"] == 600
    assert started.headers["cache-control"] == "no-store"
    # Nothing is active before the first code is confirmed.
    assert store.active_secret(ENROLL_EMAIL) is None
    assert store.pending_secret(ENROLL_EMAIL) == body["secret"]

    # A listed operator without an activated secret cannot log in yet.
    assert (
        await client.post(
            "/api/v1/auth/mfa",
            json=_login(email=ENROLL_EMAIL, code=_code(body["secret"])),
        )
    ).status_code == 403

    wrong = await client.post(
        "/api/v1/auth/enrollment/confirm", json={"email": ENROLL_EMAIL, "code": "000000"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["error_code"] == "mfa_invalid"

    confirmed = await client.post(
        "/api/v1/auth/enrollment/confirm",
        json={"email": ENROLL_EMAIL, "code": _code(body["secret"])},
    )
    assert confirmed.status_code == 204
    assert store.active_secret(ENROLL_EMAIL) == body["secret"]
    assert store.pending_secret(ENROLL_EMAIL) is None

    session = await client.post(
        "/api/v1/auth/mfa",
        json={
            "email": ENROLL_EMAIL,
            "password": PASSWORD,
            "code": _code(body["secret"]),
        },
    )
    assert session.status_code == 200, session.text


async def test_confirming_without_a_pending_enrollment_is_a_409(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/enrollment/confirm",
        json={"email": ENROLL_EMAIL, "code": _code()},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "enrollment_expired"


async def test_an_enrolled_secret_survives_a_settings_reload(
    client: AsyncClient, settings: OperatorSettings, store: SecretStore
) -> None:
    started = await client.post(
        "/api/v1/auth/enrollment", json={"email": ENROLL_EMAIL, "password": PASSWORD}
    )
    secret = started.json()["secret"]
    await client.post(
        "/api/v1/auth/enrollment/confirm",
        json={"email": ENROLL_EMAIL, "code": _code(secret)},
    )

    # The activated secret lives outside configuration: dropping the config
    # entry for it does not revoke the enrollment (the account still needs
    # its password and stays listed).
    reloaded = SecretStore(store.path)
    assert reloaded.active_secret(ENROLL_EMAIL) == secret


# -- token handling ---------------------------------------------------------


async def test_aggregate_routes_require_a_console_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


async def test_a_token_signed_with_another_secret_is_refused(client: AsyncClient) -> None:
    foreign = OperatorSettings(
        jwt_secret="another-secret-0123456789abcdefghij",
        operators=[
            OperatorAccount(
                email=EMAIL,
                display_name="Flo",
                password_hash="x",
                totp_secret=TOTP_SECRET,
            )
        ],
    )
    token = create_access_token(foreign.operator(EMAIL), foreign)  # type: ignore[arg-type]

    response = await client.get("/api/v1/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_a_removed_operator_loses_access_immediately(
    client: AsyncClient, settings: OperatorSettings, operator: OperatorAccount
) -> None:
    token = create_access_token(operator, settings)
    settings.operators = [account for account in settings.operators if account.email != EMAIL]

    response = await client.get("/api/v1/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_logout_is_stateless_and_requires_the_token(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.post("/api/v1/auth/logout")).status_code == 401
    assert (await client.post("/api/v1/auth/logout", headers=auth_headers)).status_code == 204
