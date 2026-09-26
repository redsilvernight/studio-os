"""A5 onboarding, server side of the whole journey: a self-registered User
verifies its address, waits for access with an empty project list, enrolls
its own Desktop machine without any admin, and once granted one project,
reaches exactly that project — through its session and through its machine."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import projects as projects_service

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

pytestmark = pytest.mark.isolation


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _project_ids(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    response = await client.get("/api/v1/projects", headers=headers)
    assert response.status_code == 200, response.text
    return [p["id"] for p in response.json()]


@pytest.mark.usefixtures("open_instance")
async def test_self_registered_user_reaches_only_its_projects_through_its_own_machine(
    client: AsyncClient,
    db_session: AsyncSession,
    outbox: Outbox,  # noqa: F811
    admin_auth_headers: dict[str, str],
) -> None:
    email = _email()
    assert (await _register(client, email))[0] == 202
    # Pending: the same 401 as a wrong password until the link is opened.
    assert await _login(client, email, PASSWORD) == 401
    assert (await _verify(client, outbox.last_secret(email)))[0] == 200
    session = await _jwt(client, email, PASSWORD)

    me = (await client.get("/api/v1/auth/me", headers=session)).json()
    assert me["role"] == "readonly"
    # « En attente d'accès » : active, but no project yet.
    assert await _project_ids(client, session) == []

    # Desktop enrollment without any admin: the owner is the caller.
    enrolled = await client.post(
        "/api/v1/machines", headers=session, json={"display_name": "ADA-LAPTOP · Desktop"}
    )
    assert enrolled.status_code == 201, enrolled.text
    assert enrolled.json()["owner_user_id"] == me["user_id"]
    machine = _bearer(enrolled.json()["credential"])
    assert await _project_ids(client, machine) == []

    mine = await projects_service.create_project(
        db_session, f"a5-mine-{uuid.uuid4().hex[:8]}", "Mine", None, creator=None
    )
    theirs = await projects_service.create_project(
        db_session, f"a5-theirs-{uuid.uuid4().hex[:8]}", "Theirs", None, creator=None
    )
    granted = await client.put(
        f"/api/v1/projects/{mine.id}/members/{me['user_id']}", headers=admin_auth_headers
    )
    assert granted.status_code == 201, granted.text

    for headers in (session, machine):
        assert await _project_ids(client, headers) == [str(mine.id)]
        assert (await client.get(f"/api/v1/projects/{mine.id}", headers=headers)).status_code == 200
        denied = await client.get(f"/api/v1/projects/{theirs.id}", headers=headers)
        assert denied.status_code in (403, 404), denied.text
