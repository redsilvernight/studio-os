from __future__ import annotations

from httpx import AsyncClient
from studio_operator.auth import OperatorAccount, create_access_token
from studio_operator.mfa import totp
from studio_operator.settings import OperatorSettings

from tests.operator_console.conftest import EMAIL, TOTP_SECRET


def _code() -> str:
    return totp(TOTP_SECRET)


async def test_login_with_a_valid_mfa_code_returns_an_operator_session(
    client: AsyncClient,
) -> None:
    response = await client.post("/api/v1/auth/mfa", json={"email": EMAIL, "code": _code()})

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
    response = await client.post(
        "/api/v1/auth/mfa", json={"email": "  FLO@Example.TEST ", "code": _code()}
    )
    assert response.status_code == 200, response.text


async def test_an_unknown_operator_is_refused_without_detail(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/mfa", json={"email": "inconnu@example.test", "code": _code()}
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error_code"] == "operator_not_allowed"
    assert "MFA" in detail["message"]


async def test_a_listed_operator_without_mfa_is_refused(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/mfa", json={"email": "sans-mfa@example.test", "code": _code()}
    )

    assert response.status_code == 403
    # Same envelope as an unknown account: the two cases stay indistinguishable.
    assert response.json()["detail"]["error_code"] == "operator_not_allowed"


async def test_wrong_codes_count_down_then_lock_the_account(
    client: AsyncClient,
) -> None:
    for remaining in (2, 1):
        response = await client.post("/api/v1/auth/mfa", json={"email": EMAIL, "code": "000000"})
        assert response.status_code == 401
        detail = response.json()["detail"]
        assert detail["error_code"] == "mfa_invalid"
        assert detail["attempts_remaining"] == remaining

    locked = await client.post("/api/v1/auth/mfa", json={"email": EMAIL, "code": "000000"})
    assert locked.status_code == 429
    assert locked.json()["detail"]["error_code"] == "mfa_locked"
    assert int(locked.headers["retry-after"]) > 0

    # Even the right code is refused while the lockout holds.
    still_locked = await client.post("/api/v1/auth/mfa", json={"email": EMAIL, "code": _code()})
    assert still_locked.status_code == 429


async def test_a_successful_login_resets_the_failed_attempts(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/mfa", json={"email": EMAIL, "code": "000000"})
    ok = await client.post("/api/v1/auth/mfa", json={"email": EMAIL, "code": _code()})
    assert ok.status_code == 200

    again = await client.post("/api/v1/auth/mfa", json={"email": EMAIL, "code": "000000"})
    assert again.status_code == 401
    assert again.json()["detail"]["attempts_remaining"] == 2


async def test_aggregate_routes_require_a_console_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


async def test_a_token_signed_with_another_secret_is_refused(client: AsyncClient) -> None:
    foreign = OperatorSettings(
        jwt_secret="another-secret-0123456789abcdefghij",
        operators=[OperatorAccount(email=EMAIL, display_name="Flo", totp_secret=TOTP_SECRET)],
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
