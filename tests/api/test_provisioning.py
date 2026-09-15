from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.services import provisioning as provisioning_service


async def test_developer_can_create_project(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"slug": f"proj-{uuid.uuid4().hex[:8]}", "name": "New Project"},
    )
    assert response.status_code == 201
    assert response.json()["archived"] is False


async def test_duplicate_project_slug_conflicts(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    slug = f"proj-{uuid.uuid4().hex[:8]}"
    first = await client.post(
        "/api/v1/projects", headers=auth_headers, json={"slug": slug, "name": "First"}
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/projects", headers=auth_headers, json={"slug": slug, "name": "Second"}
    )
    assert second.status_code == 409


async def test_readonly_cannot_create_project(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    readonly_user = await provisioning_service.create_user(
        db_session, "Readonly", f"{uuid.uuid4()}@example.test", "readonly"
    )
    _, token = await provisioning_service.create_machine(
        db_session, readonly_user.id, "readonly-machine"
    )
    response = await client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"slug": f"proj-{uuid.uuid4().hex[:8]}", "name": "Blocked"},
    )
    assert response.status_code == 403


async def test_bootstrap_admin_rejects_second_admin(db_session: AsyncSession) -> None:
    await provisioning_service.bootstrap_admin(
        db_session, "First Admin", f"{uuid.uuid4()}@example.test"
    )
    with pytest.raises(HTTPException) as exc_info:
        await provisioning_service.bootstrap_admin(
            db_session, "Second Admin", f"{uuid.uuid4()}@example.test"
        )
    assert exc_info.value.status_code == 409


async def test_non_admin_cannot_create_machine(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    owner_machine, _ = machine
    response = await client.post(
        "/api/v1/machines",
        headers=auth_headers,
        json={
            "owner_user_id": str(owner_machine.owner_user_id),
            "display_name": "second-machine",
        },
    )
    assert response.status_code == 403


async def test_admin_creates_and_revokes_machine(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    owner_machine, _ = machine

    create_response = await client.post(
        "/api/v1/machines",
        headers=admin_auth_headers,
        json={
            "owner_user_id": str(owner_machine.owner_user_id),
            "display_name": "second-machine",
        },
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["credential"]
    new_token = body["credential"]
    new_machine_id = body["id"]

    authenticated = await client.get(
        "/api/v1/projects", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert authenticated.status_code == 200

    revoke_response = await client.post(
        f"/api/v1/machines/{new_machine_id}/revoke", headers=admin_auth_headers
    )
    assert revoke_response.status_code == 200

    revoked = await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {new_token}"})
    assert revoked.status_code == 401


async def test_admin_creates_user(client: AsyncClient, admin_auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/users",
        headers=admin_auth_headers,
        json={
            "display_name": "New Dev",
            "email": f"{uuid.uuid4()}@example.test",
            "role": "developer",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "developer"


async def test_duplicate_user_email_conflicts(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    email = f"{uuid.uuid4()}@example.test"
    first = await client.post(
        "/api/v1/users",
        headers=admin_auth_headers,
        json={"display_name": "First", "email": email, "role": "developer"},
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/users",
        headers=admin_auth_headers,
        json={"display_name": "Second", "email": email, "role": "developer"},
    )
    assert second.status_code == 409
