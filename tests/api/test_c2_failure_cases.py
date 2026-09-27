"""C2 failure cases, server side of the new-user journey: a self-registered
User whose session is expired or forged, whose account is disabled while it
works, who tries every self-service door to more privilege, or who reads a
project it was never granted — always refused, and nothing it tried leaves a
trace. The Desktop update failures (network, invalid update) are covered by
`desktop/src-tauri/src/updater.rs` (matrix in `docs/DESKTOP_C2_E2E.md`)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.project import ProjectModel
from studio_api.jwt_auth import ALGORITHM
from studio_api.services import projects as projects_service
from studio_api.settings import Settings

from tests.api.test_public_registration import (  # noqa: F401 (fixtures)
    PASSWORD,
    Outbox,
    _email,
    _jwt,
    _login,
    _register,
    _verify,
    open_instance,
    outbox,
)

pytestmark = [pytest.mark.isolation, pytest.mark.usefixtures("open_instance")]

DENIED = (403, 404)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _new_user(client: AsyncClient, outbox: Outbox) -> tuple[str, dict[str, str], str]:  # noqa: F811
    """Register and verify a fresh address; returns (email, session, user_id)."""
    email = _email()
    assert (await _register(client, email))[0] == 202
    assert (await _verify(client, outbox.last_secret(email)))[0] == 200
    session = await _jwt(client, email, PASSWORD)
    me = await client.get("/api/v1/auth/me", headers=session)
    assert me.status_code == 200, me.text
    return email, session, me.json()["user_id"]


async def _own_machine(client: AsyncClient, session: dict[str, str]) -> dict[str, str]:
    enrolled = await client.post(
        "/api/v1/machines", headers=session, json={"display_name": "C2 · Desktop"}
    )
    assert enrolled.status_code == 201, enrolled.text
    return _bearer(enrolled.json()["credential"])


async def _project(db_session: AsyncSession, tag: str) -> ProjectModel:
    return await projects_service.create_project(
        db_session, f"c2-{tag}-{uuid.uuid4().hex[:8]}", tag, None, creator=None
    )


async def _me_status(client: AsyncClient, headers: dict[str, str]) -> int:
    return (await client.get("/api/v1/auth/me", headers=headers)).status_code


# --- Session ----------------------------------------------------------------


async def test_expired_or_forged_session_is_refused_and_a_new_login_works(
    client: AsyncClient,
    outbox: Outbox,  # noqa: F811
    open_instance: Settings,  # noqa: F811
) -> None:
    email, session, _ = await _new_user(client, outbox)
    token = session["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, options={"verify_signature": False})
    secret = open_instance.jwt_secret
    past = datetime.now(UTC) - timedelta(hours=1)

    expired = jwt.encode(
        {**claims, "iat": past - timedelta(minutes=15), "exp": past}, secret, algorithm=ALGORITHM
    )
    wrong_key = jwt.encode(claims, secret + "-not-the-server-key", algorithm=ALGORITHM)
    unsigned = jwt.encode(claims, key=None, algorithm="none")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    for forged in (expired, wrong_key, unsigned, tampered, "not-a-token"):
        response = await client.get("/api/v1/auth/me", headers=_bearer(forged))
        assert response.status_code == 401, forged
        assert "user_id" not in response.text

    # None of the forgeries touched the genuine session, and logging in again
    # (what the Desktop asks for on a 401) gives a working one.
    assert await _me_status(client, session) == 200
    assert await _me_status(client, await _jwt(client, email, PASSWORD)) == 200


# --- Disabled account -------------------------------------------------------


async def test_account_disabled_mid_session_loses_session_machine_and_projects(
    client: AsyncClient,
    db_session: AsyncSession,
    outbox: Outbox,  # noqa: F811
    admin_auth_headers: dict[str, str],
) -> None:
    email, session, user_id = await _new_user(client, outbox)
    machine = await _own_machine(client, session)
    mine = await _project(db_session, "mine")
    granted = await client.put(
        f"/api/v1/projects/{mine.id}/members/{user_id}", headers=admin_auth_headers
    )
    assert granted.status_code == 201, granted.text
    for headers in (session, machine):
        assert (await client.get(f"/api/v1/projects/{mine.id}", headers=headers)).status_code == 200

    disabled = await client.post(f"/api/v1/users/{user_id}/disable", headers=admin_auth_headers)
    assert disabled.status_code == 200, disabled.text

    for headers in (session, machine):
        assert await _me_status(client, headers) == 401
        assert (await client.get(f"/api/v1/projects/{mine.id}", headers=headers)).status_code == 401
    # Same answer as a wrong password: the account state is not disclosed.
    assert await _login(client, email, PASSWORD) == 401
    assert await _login(client, email, "wrong password entirely") == 401
    # A disabled account cannot enroll a new machine either.
    enrolled = await client.post("/api/v1/machines", headers=session, json={"display_name": "x"})
    assert enrolled.status_code == 401

    enabled = await client.post(f"/api/v1/users/{user_id}/enable", headers=admin_auth_headers)
    assert enabled.status_code == 200, enabled.text
    # The machine comes back; the session revoked by the disable does not.
    assert await _me_status(client, machine) == 200
    assert await _me_status(client, session) == 401
    fresh = await _jwt(client, email, PASSWORD)
    assert (await client.get(f"/api/v1/projects/{mine.id}", headers=fresh)).status_code == 200


# --- Privilege escalation ---------------------------------------------------


async def test_self_registered_user_cannot_gain_any_privilege_through_the_api(
    client: AsyncClient,
    db_session: AsyncSession,
    outbox: Outbox,  # noqa: F811
    admin_auth_headers: dict[str, str],
) -> None:
    _, session, user_id = await _new_user(client, outbox)
    machine = await _own_machine(client, session)
    admin_id = (await client.get("/api/v1/auth/me", headers=admin_auth_headers)).json()["user_id"]
    admin_machine_id = (await client.get("/api/v1/machines/me", headers=admin_auth_headers)).json()[
        "id"
    ]
    mine = await _project(db_session, "mine")
    theirs = await _project(db_session, "theirs")
    assert (
        await client.put(
            f"/api/v1/projects/{mine.id}/members/{user_id}", headers=admin_auth_headers
        )
    ).status_code == 201

    for headers in (session, machine):
        attempts = [
            # Grant itself a project, or remove someone else from one.
            ("PUT", f"/api/v1/projects/{theirs.id}/members/{user_id}", None),
            ("DELETE", f"/api/v1/projects/{mine.id}/members/{admin_id}", None),
            # Create a project (it would become a member of it).
            ("POST", "/api/v1/projects", {"slug": f"c2-x-{uuid.uuid4().hex[:8]}", "name": "x"}),
            # User administration: directory, creation, state of the admin.
            ("GET", "/api/v1/users", None),
            (
                "POST",
                "/api/v1/users",
                {"display_name": "Evil", "email": _email(), "role": "admin"},
            ),
            ("POST", f"/api/v1/users/{admin_id}/disable", None),
            ("POST", f"/api/v1/users/{admin_id}/revoke-sessions", None),
            ("GET", f"/api/v1/users/{admin_id}/memberships", None),
            # A machine owned by the admin (it would inherit the admin role),
            # or revoking the admin's machine.
            ("POST", "/api/v1/machines", {"display_name": "x", "owner_user_id": admin_id}),
            ("POST", f"/api/v1/machines/{admin_machine_id}/revoke", None),
            # A readonly member does not write in its own project.
            ("POST", "/api/v1/tasks", {"project_id": str(mine.id), "title": "x"}),
        ]
        for method, path, body in attempts:
            response = await client.request(
                method,
                path,
                headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
                json=body,
            )
            assert response.status_code in DENIED, f"{method} {path}: {response.text}"

    # Nothing changed: same role, same single project, the admin untouched.
    me = (await client.get("/api/v1/auth/me", headers=session)).json()
    assert me["role"] == "readonly"
    projects = await client.get("/api/v1/projects", headers=session)
    assert [p["id"] for p in projects.json()] == [str(mine.id)]
    assert await _me_status(client, admin_auth_headers) == 200
    members = await client.get(f"/api/v1/projects/{mine.id}/members", headers=admin_auth_headers)
    assert {m["user_id"] for m in members.json()} == {user_id}
    theirs_members = await client.get(
        f"/api/v1/projects/{theirs.id}/members", headers=admin_auth_headers
    )
    assert theirs_members.json() == []


# --- Forbidden project ------------------------------------------------------


async def test_a_project_never_granted_is_unreadable_through_every_route(
    client: AsyncClient,
    db_session: AsyncSession,
    outbox: Outbox,  # noqa: F811
    admin_auth_headers: dict[str, str],
) -> None:
    _, session, _ = await _new_user(client, outbox)
    machine = await _own_machine(client, session)
    theirs = await _project(db_session, "theirs")
    task = await client.post(
        "/api/v1/tasks",
        headers=admin_auth_headers,
        json={"project_id": str(theirs.id), "title": "secret task"},
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]

    for headers in (session, machine):
        for path in (
            f"/api/v1/projects/{theirs.id}",
            f"/api/v1/projects/{theirs.id}/state",
            f"/api/v1/projects/{theirs.id}/members",
            f"/api/v1/tasks/{task_id}",
        ):
            response = await client.get(path, headers=headers)
            assert response.status_code in DENIED, f"{path}: {response.text}"
            assert "secret task" not in response.text
        for path in ("/api/v1/tasks", "/api/v1/decisions", "/api/v1/events"):
            response = await client.get(
                path, headers=headers, params={"project_id": str(theirs.id)}
            )
            if response.status_code == 200:
                assert response.json() in ([], {"items": []}), f"{path}: {response.text}"
            else:
                assert response.status_code in DENIED, f"{path}: {response.text}"
            assert "secret task" not in response.text
        # Writing into it is refused the same way.
        claim = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=headers)
        assert claim.status_code in DENIED, claim.text
