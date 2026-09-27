"""A5 machine self-service: a User creates and revokes its own machines; the
owner is always derived from the authenticated principal for a non-admin."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel

FORBIDDEN_CREATE = {"error_code": "forbidden", "resource": "machine", "action": "create"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("name_self", [False, True])
async def test_a_user_creates_its_own_machine(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    name_self: bool,
) -> None:
    owner = machine[0].owner_user_id
    body: dict[str, str] = {"display_name": "FLO-LAPTOP · Claude Code"}
    if name_self:
        body["owner_user_id"] = str(owner)
    response = await client.post("/api/v1/machines", headers=auth_headers, json=body)
    assert response.status_code == 201
    created = response.json()
    assert created["owner_user_id"] == str(owner)
    assert created["credential"]

    me = await client.get("/api/v1/machines/me", headers=_bearer(created["credential"]))
    assert me.status_code == 200
    assert me.json()["id"] == created["id"]


async def test_a_non_admin_never_chooses_another_owner(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    for owner in (other_machine[0].owner_user_id, uuid.uuid4()):
        response = await client.post(
            "/api/v1/machines",
            headers=auth_headers,
            json={"owner_user_id": str(owner), "display_name": "hijack"},
        )
        # Same answer for an existing and a nonexistent User: no lookup, no oracle.
        assert response.status_code == 403
        assert response.json()["detail"] == FORBIDDEN_CREATE


async def test_a_readonly_user_self_serves_and_its_machine_stays_readonly(
    client: AsyncClient,
    readonly_auth_headers: dict[str, str],
    readonly_machine: tuple[MachineModel, str],
) -> None:
    response = await client.post(
        "/api/v1/machines", headers=readonly_auth_headers, json={"display_name": "ro-tool"}
    )
    assert response.status_code == 201
    created = response.json()
    assert created["owner_user_id"] == str(readonly_machine[0].owner_user_id)

    write = await client.post(
        "/api/v1/projects",
        headers=_bearer(created["credential"]),
        json={"slug": f"proj-{uuid.uuid4().hex[:8]}", "name": "Blocked"},
    )
    assert write.status_code == 403

    revoke = await client.post(
        f"/api/v1/machines/{created['id']}/revoke", headers=readonly_auth_headers
    )
    assert revoke.status_code == 200


async def test_an_agent_never_creates_nor_revokes_machines(
    client: AsyncClient,
    agent_auth_headers: dict[str, str],
    agent_machine: tuple[MachineModel, str],
) -> None:
    create = await client.post(
        "/api/v1/machines", headers=agent_auth_headers, json={"display_name": "x"}
    )
    assert create.status_code == 403
    assert create.json()["detail"] == FORBIDDEN_CREATE

    revoke = await client.post(
        f"/api/v1/machines/{agent_machine[0].id}/revoke", headers=agent_auth_headers
    )
    assert revoke.status_code == 403


async def test_a_user_revokes_its_own_machine(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (
        await client.post("/api/v1/machines", headers=auth_headers, json={"display_name": "t"})
    ).json()
    revoke = await client.post(f"/api/v1/machines/{created['id']}/revoke", headers=auth_headers)
    assert revoke.status_code == 200
    assert (
        await client.get("/api/v1/machines/me", headers=_bearer(created["credential"]))
    ).status_code == 401


async def test_another_users_machine_is_indistinguishable_from_a_missing_one(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    theirs = await client.post(
        f"/api/v1/machines/{other_machine[0].id}/revoke", headers=auth_headers
    )
    missing = await client.post(f"/api/v1/machines/{uuid.uuid4()}/revoke", headers=auth_headers)
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()

    still_valid = await client.get("/api/v1/machines/me", headers=_bearer(other_machine[1]))
    assert still_valid.status_code == 200


async def test_admin_keeps_provisioning_for_any_user(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    other_user = other_machine[0].owner_user_id
    created = await client.post(
        "/api/v1/machines",
        headers=admin_auth_headers,
        json={"owner_user_id": str(other_user), "display_name": "for-other"},
    )
    assert created.status_code == 201
    assert created.json()["owner_user_id"] == str(other_user)

    unknown = await client.post(
        "/api/v1/machines",
        headers=admin_auth_headers,
        json={"owner_user_id": str(uuid.uuid4()), "display_name": "nobody"},
    )
    assert unknown.status_code == 404

    revoke = await client.post(
        f"/api/v1/machines/{other_machine[0].id}/revoke", headers=admin_auth_headers
    )
    assert revoke.status_code == 200
