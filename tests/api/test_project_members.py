"""Project members administration (DEC-0103, task 0324dbb3): admin-only
`/projects/{id}/members` and `studio-admin project grant|revoke|members`.
Deny by default: no automatic backfill grants (`isolation` marker)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api import admin_cli
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import event_stream
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

from tests.api.test_admin_cli import _bind_session

pytestmark = pytest.mark.isolation

UNKNOWN = "00000000-0000-4000-8000-000000000000"


async def _owner_id(client: AsyncClient, headers: dict[str, str]) -> str:
    me = await client.get("/api/v1/machines/me", headers=headers)
    return str(me.json()["owner_user_id"])


async def test_admin_grants_lists_and_revokes(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    user_id = str(machine[0].owner_user_id)
    base = f"/api/v1/projects/{project.id}/members"
    project_url = f"/api/v1/projects/{project.id}"
    assert (await client.get(project_url, headers=auth_headers)).status_code == 403

    granted = await client.put(f"{base}/{user_id}", headers=admin_auth_headers)
    assert granted.status_code == 201, granted.text
    body = granted.json()
    assert body["user_id"] == user_id
    assert body["project_id"] == str(project.id)
    assert body["granted_by_user_id"] == await _owner_id(client, admin_auth_headers)
    assert body["user_email"] and body["user_display_name"]
    assert (await client.get(project_url, headers=auth_headers)).status_code == 200

    listed = await client.get(base, headers=admin_auth_headers)
    assert listed.status_code == 200
    assert [(m["user_id"], m["user_email"]) for m in listed.json()] == [
        (user_id, body["user_email"])
    ]

    revoked = await client.delete(f"{base}/{user_id}", headers=admin_auth_headers)
    assert revoked.status_code == 204
    assert (await client.get(base, headers=admin_auth_headers)).json() == []
    assert (await client.get(project_url, headers=auth_headers)).status_code == 403

    again = await client.delete(f"{base}/{user_id}", headers=admin_auth_headers)
    assert again.status_code == 204


async def test_regrant_keeps_original_membership(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    user_id = machine[0].owner_user_id
    first_admin = await provisioning_service.create_user(
        db_session, "First Admin", f"{uuid.uuid4()}@example.test", "admin"
    )
    _, created = await projects_service.grant_member(
        db_session, project.id, user_id, granted_by_user_id=first_admin.id
    )
    assert created

    again = await client.put(
        f"/api/v1/projects/{project.id}/members/{user_id}", headers=admin_auth_headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["granted_by_user_id"] == str(first_admin.id)
    listed = await client.get(f"/api/v1/projects/{project.id}/members", headers=admin_auth_headers)
    assert len(listed.json()) == 1


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_non_admin_is_forbidden_before_lookup(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    method: str,
) -> None:
    """A developer — even the creator of the project — never manages members."""
    created = await client.post(
        "/api/v1/projects",
        json={"slug": f"mem-{uuid.uuid4().hex[:8]}", "name": "M"},
        headers=auth_headers,
    )
    user_id = machine[0].owner_user_id
    for pid in (created.json()["id"], UNKNOWN):
        path = f"/api/v1/projects/{pid}/members"
        if method != "GET":
            path += f"/{user_id}"
        response = await client.request(method, path, headers=auth_headers)
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["error_code"] == "forbidden"


async def test_unknown_project_or_user_is_404_for_admin(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    user_id = machine[0].owner_user_id
    unknown_list = await client.get(
        f"/api/v1/projects/{UNKNOWN}/members", headers=admin_auth_headers
    )
    assert unknown_list.status_code == 404
    for method in ("PUT", "DELETE"):
        unknown_project = await client.request(
            method, f"/api/v1/projects/{UNKNOWN}/members/{user_id}", headers=admin_auth_headers
        )
        assert unknown_project.status_code == 404
        unknown_user = await client.request(
            method, f"/api/v1/projects/{project.id}/members/{UNKNOWN}", headers=admin_auth_headers
        )
        assert unknown_user.status_code == 404


async def test_revoke_closes_open_streams(
    db_session: AsyncSession, machine: tuple[MachineModel, str], project: ProjectModel
) -> None:
    user_id = machine[0].owner_user_id
    admin = await provisioning_service.create_user(
        db_session, "Admin", f"{uuid.uuid4()}@example.test", "admin"
    )
    await projects_service.grant_member(
        db_session, project.id, user_id, granted_by_user_id=admin.id
    )
    queue = event_stream.subscribe()
    try:
        assert await projects_service.revoke_member(db_session, project.id, user_id)
        item = await event_stream.receive(queue, timeout=1)
        assert item == event_stream.AccessRevoked(user_id=user_id, project_id=project.id)
        assert not await projects_service.revoke_member(db_session, project.id, user_id)
        assert queue.empty()  # an idempotent no-op signals nothing
    finally:
        event_stream.unsubscribe(queue)


async def test_cli_grant_revoke_and_list(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    project: ProjectModel,
) -> None:
    _bind_session(monkeypatch, db_session)
    admin = await provisioning_service.create_user(
        db_session, "Admin", f"{uuid.uuid4()}@example.test", "admin"
    )
    dev = await provisioning_service.create_user(
        db_session, "Dev", f"{uuid.uuid4()}@example.test", "developer"
    )

    await admin_cli._grant_project_member(project.slug, dev.email.upper(), admin.email)
    await admin_cli._grant_project_member(str(project.id), dev.email, admin.email)
    members = await projects_service.list_members(db_session, project.id)
    assert [(m.user_id, m.granted_by_user_id) for m in members] == [(dev.id, admin.id)]

    await admin_cli._list_project_members(project.slug)
    await admin_cli._revoke_project_member(project.slug, dev.email)
    await admin_cli._revoke_project_member(project.slug, dev.email)
    assert await projects_service.list_members(db_session, project.id) == []

    out = capsys.readouterr().out
    assert f"granted: {dev.email} -> {project.slug}" in out
    assert "already a member" in out
    assert str(dev.id) in out
    assert f"revoked: {dev.email}" in out
    assert "not a member" in out


async def test_cli_grant_requires_an_admin_and_known_targets(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, project: ProjectModel
) -> None:
    _bind_session(monkeypatch, db_session)
    dev = await provisioning_service.create_user(
        db_session, "Dev", f"{uuid.uuid4()}@example.test", "developer"
    )
    with pytest.raises(SystemExit):
        await admin_cli._grant_project_member(project.slug, dev.email, dev.email)
    with pytest.raises(SystemExit):
        await admin_cli._grant_project_member("no-such-project", dev.email, dev.email)
    with pytest.raises(SystemExit):
        await admin_cli._revoke_project_member(project.slug, "nobody@example.test")
    assert await projects_service.list_members(db_session, project.id) == []
