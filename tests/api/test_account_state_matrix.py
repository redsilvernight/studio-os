"""Role × account state × project access over HTTP (A3, task 0e337d4b).

The account state decides whether a principal exists at all (machine token
and dashboard login); project access (DEC-0103) only applies to an active
account and stays independent of the state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.project import ProjectModel
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

pytestmark = pytest.mark.isolation

ROLES = ("admin", "developer", "readonly", "agent")
STATES = ("active", "pending", "disabled")
_PASSWORD = "matrix-secret"


async def _account(
    db_session: AsyncSession, role: str, state: str, project: ProjectModel, member: bool
) -> tuple[str, str]:
    user = await provisioning_service.create_user(
        db_session, "Matrix User", f"{uuid.uuid4()}@example.test", role
    )
    await provisioning_service.set_user_password(db_session, user.email, _PASSWORD)
    _machine, token = await provisioning_service.create_machine(db_session, user.id, "matrix")
    if member:
        await projects_service.grant_member(
            db_session, project.id, user.id, granted_by_user_id=None
        )
    if state == "pending":
        user.email_verified_at = None
        await db_session.flush()
    elif state == "disabled":
        await provisioning_service.disable_user(db_session, user.email)
    else:
        assert user.email_verified_at is not None and user.email_verified_at <= datetime.now(UTC)
    return user.email, token


@pytest.mark.parametrize("member", [True, False])
@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("role", ROLES)
async def test_http_matrix(
    client: AsyncClient,
    db_session: AsyncSession,
    project: ProjectModel,
    role: str,
    state: str,
    member: bool,
) -> None:
    email, token = await _account(db_session, role, state, project, member)
    machine = {"Authorization": f"Bearer {token}"}
    login = await client.post("/api/v1/auth/token", json={"email": email, "password": _PASSWORD})

    if state != "active":
        assert login.status_code == 401
        assert login.json() == {"detail": "invalid email or password"}
        for path in ("/api/v1/auth/me", "/api/v1/projects", f"/api/v1/projects/{project.id}"):
            refused = await client.get(path, headers=machine)
            assert refused.status_code == 401, path
            assert refused.json() == {"detail": "invalid or revoked machine token"}
        return

    assert login.status_code == 200
    dashboard = {"Authorization": f"Bearer {login.json()['access_token']}"}
    sees_project = member or role == "admin"
    for headers in (machine, dashboard):
        me = await client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200 and me.json()["role"] == role
        listed = await client.get("/api/v1/projects", headers=headers)
        assert (str(project.id) in {p["id"] for p in listed.json()}) is sees_project
        detail = await client.get(f"/api/v1/projects/{project.id}", headers=headers)
        assert detail.status_code == (200 if sees_project else 403)
        queue = await client.get(
            "/api/v1/review-queue", params={"project_id": str(project.id)}, headers=headers
        )
        assert queue.status_code == (200 if sees_project else 403)
        if not sees_project:
            assert detail.json()["detail"]["resource"] == "project"
