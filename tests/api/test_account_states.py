"""Account states and account administration (A3, DU-0/A, tasks f1c0664c and
4cb7a6bd): normalized emails, derived status, admin-only state and access
actions, and no self-modification of role, state or access."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.main import app
from studio_api.services import event_stream
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

from tests.api.test_project_members import _owner_id

_PASSWORD = "secret123"
UNKNOWN = "00000000-0000-4000-8000-000000000000"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _user(db_session: AsyncSession, role: str = "developer") -> UserModel:
    user = await provisioning_service.create_user(
        db_session, "Account User", f"{uuid.uuid4()}@example.test", role
    )
    return await provisioning_service.set_user_password(db_session, user.email, _PASSWORD)


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/token", json={"email": email, "password": _PASSWORD})
    assert response.status_code == 200, response.text
    return _bearer(response.json()["access_token"])


async def test_emails_are_normalized_and_unique_regardless_of_case(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    local = uuid.uuid4().hex
    created = await client.post(
        "/api/v1/users",
        json={"display_name": "Norma", "email": f"  {local}@Example.TEST ", "role": "developer"},
        headers=admin_auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["email"] == f"{local}@example.test"
    assert created.json()["status"] == "active"
    assert created.json()["email_verified_at"] is not None
    assert created.json()["disabled_at"] is None

    duplicate = await client.post(
        "/api/v1/users",
        json={"display_name": "Norma 2", "email": f"{local.upper()}@EXAMPLE.test", "role": "readonly"},
        headers=admin_auth_headers,
    )
    assert duplicate.status_code == 409

    found = await provisioning_service.get_user_by_email(db_session, f" {local.upper()}@example.TEST")
    assert found is not None and str(found.id) == created.json()["id"]
    await provisioning_service.set_user_password(db_session, f"{local}@EXAMPLE.test", _PASSWORD)
    await _login(client, f" {local.upper()}@Example.Test ")


async def test_database_refuses_a_case_variant_email(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                insert(UserModel).values(
                    id=uuid.uuid4(),
                    display_name="Variant",
                    email=user.email.upper(),
                    role="readonly",
                    version=1,
                )
            )


async def test_directory_exposes_derived_status(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    active = await _user(db_session)
    pending = await _user(db_session)
    pending.email_verified_at = None
    disabled = await _user(db_session)
    await provisioning_service.disable_account(db_session, disabled)
    await db_session.flush()

    listed = await client.get("/api/v1/users", params={"limit": 200}, headers=admin_auth_headers)
    by_id = {u["id"]: u for u in listed.json()}
    assert by_id[str(active.id)]["status"] == "active"
    assert by_id[str(pending.id)]["status"] == "pending"
    assert by_id[str(pending.id)]["email_verified_at"] is None
    assert by_id[str(disabled.id)]["status"] == "disabled"
    assert by_id[str(disabled.id)]["disabled_at"] is not None


async def test_admin_disable_blocks_everything_until_enable(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    user = await _user(db_session)
    _machine, token = await provisioning_service.create_machine(db_session, user.id, "laptop")
    jwt_headers = await _login(client, user.email)
    queue = event_stream.subscribe()
    try:
        disabled = await client.post(
            f"/api/v1/users/{user.id}/disable", headers=admin_auth_headers
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "disabled"
        assert queue.get_nowait() == event_stream.UserRevalidation(user_id=user.id)
    finally:
        event_stream.unsubscribe(queue)

    for headers in (jwt_headers, _bearer(token)):
        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    login = await client.post(
        "/api/v1/auth/token", json={"email": user.email, "password": _PASSWORD}
    )
    assert login.status_code == 401
    again = await client.post(f"/api/v1/users/{user.id}/disable", headers=admin_auth_headers)
    assert again.status_code == 200
    assert again.json()["version"] == disabled.json()["version"]

    enabled = await client.post(f"/api/v1/users/{user.id}/enable", headers=admin_auth_headers)
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"
    assert (await client.get("/api/v1/auth/me", headers=_bearer(token))).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=jwt_headers)).status_code == 401
    await _login(client, user.email)


async def test_enable_keeps_an_unverified_account_pending(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    user = await _user(db_session)
    await provisioning_service.disable_account(db_session, user)
    user.email_verified_at = None
    await db_session.flush()

    enabled = await client.post(f"/api/v1/users/{user.id}/enable", headers=admin_auth_headers)

    assert enabled.status_code == 200
    assert enabled.json()["status"] == "pending"
    login = await client.post(
        "/api/v1/auth/token", json={"email": user.email, "password": _PASSWORD}
    )
    assert login.status_code == 401


async def test_admin_revoke_sessions_keeps_machine_tokens(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    user = await _user(db_session)
    _machine, token = await provisioning_service.create_machine(db_session, user.id, "laptop")
    jwt_headers = await _login(client, user.email)

    revoked = await client.post(
        f"/api/v1/users/{user.id}/revoke-sessions", headers=admin_auth_headers
    )

    assert revoked.status_code == 200
    assert revoked.json()["status"] == "active"
    assert (await client.get("/api/v1/auth/me", headers=jwt_headers)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=_bearer(token))).status_code == 200


async def test_admin_lists_a_users_memberships(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    user = await _user(db_session)
    empty = await client.get(f"/api/v1/users/{user.id}/memberships", headers=admin_auth_headers)
    assert empty.status_code == 200 and empty.json() == []

    granted = await client.put(
        f"/api/v1/projects/{project.id}/members/{user.id}", headers=admin_auth_headers
    )
    assert granted.status_code == 201

    listed = await client.get(f"/api/v1/users/{user.id}/memberships", headers=admin_auth_headers)
    assert [(m["project_id"], m["user_email"]) for m in listed.json()] == [
        (str(project.id), user.email)
    ]
    unknown = await client.get(f"/api/v1/users/{UNKNOWN}/memberships", headers=admin_auth_headers)
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["error_code"] == "not_found"


@pytest.mark.parametrize("action", ["disable", "enable", "revoke-sessions"])
async def test_state_actions_are_admin_only_and_404_on_unknown(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    action: str,
) -> None:
    target = await _user(db_session)
    denied = await client.post(f"/api/v1/users/{target.id}/{action}", headers=auth_headers)
    assert denied.status_code == 403
    listing = await client.get(f"/api/v1/users/{target.id}/memberships", headers=auth_headers)
    assert listing.status_code == 403
    unknown = await client.post(f"/api/v1/users/{UNKNOWN}/{action}", headers=admin_auth_headers)
    assert unknown.status_code == 404
    await db_session.refresh(target)
    assert target.status == "active"


def _mutating_user_targeted_routes() -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if "{user_id}" not in path:
            continue
        routes.extend((method, path) for method in sorted(methods - {"GET", "HEAD", "OPTIONS"}))
    return routes


def test_every_user_targeted_mutation_is_covered() -> None:
    assert set(_mutating_user_targeted_routes()) == {
        ("POST", "/api/v1/users/{user_id}/disable"),
        ("POST", "/api/v1/users/{user_id}/enable"),
        ("POST", "/api/v1/users/{user_id}/revoke-sessions"),
        ("PUT", "/api/v1/projects/{project_id}/members/{user_id}"),
        ("DELETE", "/api/v1/projects/{project_id}/members/{user_id}"),
    }
    assert not [
        (method, path)
        for method, path in (
            (m, getattr(r, "path", "")) for r in app.routes for m in getattr(r, "methods", ())
        )
        if re.fullmatch(r"/api/v1/(users|auth)(/.*)?", path) and method in {"PATCH", "PUT"}
    ]


@pytest.mark.parametrize(("method", "path"), _mutating_user_targeted_routes())
async def test_no_endpoint_modifies_the_callers_own_account(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    method: str,
    path: str,
) -> None:
    admin_id = uuid.UUID(await _owner_id(client, admin_auth_headers))
    await projects_service.grant_member(
        db_session, project.id, admin_id, granted_by_user_id=admin_id
    )
    before = await db_session.get(UserModel, admin_id, populate_existing=True)
    assert before is not None
    snapshot = (before.role, before.status, before.auth_version, before.version)

    response = await client.request(
        method,
        path.format(user_id=admin_id, project_id=project.id),
        headers=admin_auth_headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["error_code"] == "self_modification_forbidden"
    after = await db_session.get(UserModel, admin_id, populate_existing=True)
    assert after is not None
    assert (after.role, after.status, after.auth_version, after.version) == snapshot
    memberships = await projects_service.list_user_memberships(db_session, admin_id)
    assert [m.project_id for m in memberships] == [project.id]
    assert (await client.get("/api/v1/auth/me", headers=admin_auth_headers)).status_code == 200


async def test_active_verified_account_without_membership_sees_an_empty_state(
    client: AsyncClient, db_session: AsyncSession, project: ProjectModel
) -> None:
    user = await _user(db_session, "readonly")
    headers = await _login(client, user.email)

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    for path in ("/api/v1/projects", "/api/v1/tasks", "/api/v1/review-queue", "/api/v1/machines"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
    assert (await client.get("/api/v1/projects", headers=headers)).json() == []
    assert (await client.get("/api/v1/review-queue", headers=headers)).json()["items"] == []
    machines = (await client.get("/api/v1/machines", headers=headers)).json()
    assert {m["owner_user_id"] for m in machines} == {str(user.id)}
    denied = await client.get(f"/api/v1/projects/{project.id}", headers=headers)
    assert denied.status_code == 403


async def test_machine_of_a_disabled_owner_is_refused(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    admin_auth_headers: dict[str, str],
) -> None:
    machine_model, token = machine
    await client.post(
        f"/api/v1/users/{machine_model.owner_user_id}/disable", headers=admin_auth_headers
    )
    response = await client.get("/api/v1/machines/me", headers=_bearer(token))
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid or revoked machine token"}
