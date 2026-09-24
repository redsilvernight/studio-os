"""Project isolation, lot 1 (DEC-0100 / server DEC-0103): memberships, the
principal's project scope and the `/projects` surface. Deny by default: these
tests run without the automatic backfill grants (`isolation` marker)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import ALL_PROJECTS, load_principal

pytestmark = pytest.mark.isolation

FORBIDDEN_READ = {"error_code": "forbidden", "resource": "project", "action": "read"}
UNKNOWN = "00000000-0000-0000-0000-000000000000"


async def _create(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    response = await client.post(
        "/api/v1/projects",
        json={"slug": f"iso-{uuid.uuid4().hex[:8]}", "name": "Iso"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_creator_becomes_member_with_provenance(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project = await _create(client, auth_headers)
    rows = (
        (
            await db_session.execute(
                select(ProjectMembershipModel).where(
                    ProjectMembershipModel.project_id == uuid.UUID(project["id"])
                )
            )
        )
        .scalars()
        .all()
    )
    owner = machine[0].owner_user_id
    assert [(r.user_id, r.granted_by_user_id) for r in rows] == [(owner, owner)]


async def test_admin_creator_is_member_too(
    client: AsyncClient, admin_auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """A later demotion keeps the admin's access consistent (DEC-0100 §5)."""
    project = await _create(client, admin_auth_headers)
    rows = (
        await db_session.execute(
            select(ProjectMembershipModel.user_id).where(
                ProjectMembershipModel.project_id == uuid.UUID(project["id"])
            )
        )
    ).all()
    assert len(rows) == 1


async def test_list_is_filtered_to_memberships(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
) -> None:
    mine = await _create(client, auth_headers)
    theirs = await _create(client, other_auth_headers)

    listed = {p["id"] for p in (await client.get("/api/v1/projects", headers=auth_headers)).json()}
    assert mine["id"] in listed
    assert theirs["id"] not in listed

    admin_listed = {
        p["id"] for p in (await client.get("/api/v1/projects", headers=admin_auth_headers)).json()
    }
    assert {mine["id"], theirs["id"]} <= admin_listed


@pytest.mark.parametrize("suffix", ["", "/state"])
async def test_non_member_gets_403_without_existence_oracle(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    suffix: str,
) -> None:
    project = await _create(client, auth_headers)

    assert (
        await client.get(f"/api/v1/projects/{project['id']}{suffix}", headers=auth_headers)
    ).status_code == 200

    inaccessible = await client.get(
        f"/api/v1/projects/{project['id']}{suffix}", headers=other_auth_headers
    )
    nonexistent = await client.get(
        f"/api/v1/projects/{UNKNOWN}{suffix}", headers=other_auth_headers
    )
    assert inaccessible.status_code == nonexistent.status_code == 403
    assert inaccessible.json()["detail"] == nonexistent.json()["detail"] == FORBIDDEN_READ


async def test_admin_gets_404_on_nonexistent_project(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    response = await client.get(f"/api/v1/projects/{UNKNOWN}", headers=admin_auth_headers)
    assert response.status_code == 404


async def test_project_scope_by_role(db_session: AsyncSession) -> None:
    admin = await provisioning_service.create_user(
        db_session, "Admin", f"{uuid.uuid4()}@example.test", "admin"
    )
    dev = await provisioning_service.create_user(
        db_session, "Dev", f"{uuid.uuid4()}@example.test", "developer"
    )
    admin_machine, _ = await provisioning_service.create_machine(db_session, admin.id, "a")
    dev_machine, _ = await provisioning_service.create_machine(db_session, dev.id, "d")

    assert (await load_principal(db_session, admin_machine)).project_scope is ALL_PROJECTS
    assert (await load_principal(db_session, dev_machine)).project_scope == frozenset()

    project = await projects_service.create_project(
        db_session, f"iso-{uuid.uuid4().hex[:8]}", "Iso", None, creator=dev
    )
    assert (await load_principal(db_session, dev_machine)).project_scope == frozenset({project.id})
