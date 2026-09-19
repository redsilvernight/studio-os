from __future__ import annotations

from datetime import UTC, datetime

from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel


async def test_list_machines_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/machines", headers={"X-Forwarded-For": "203.0.113.42"})
    assert response.status_code == 401


async def test_never_seen_machine_is_listed_offline_without_secrets(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    response = await client.get("/api/v1/machines", headers=auth_headers)
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    row = rows[str(machine_model.id)]
    assert row["display_name"] == machine_model.display_name
    assert row["owner_user_id"] == str(machine_model.owner_user_id)
    assert row["last_seen_at"] is None
    assert row["status"] == "offline"
    assert "credential" not in row
    assert "credential_hash" not in row


async def test_heartbeat_feeds_listed_status_and_last_seen(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    heartbeat = await client.post(
        "/api/v1/heartbeats",
        headers=auth_headers,
        json={
            "machine_id": str(machine_model.id),
            "client_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert heartbeat.status_code == 200

    response = await client.get("/api/v1/machines", headers=auth_headers)
    row = next(item for item in response.json() if item["id"] == str(machine_model.id))
    assert row["status"] == "online"
    assert row["last_seen_at"] is not None


async def test_readonly_machine_may_list_machines(
    client: AsyncClient,
    readonly_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    response = await client.get("/api/v1/machines", headers=readonly_auth_headers)
    assert response.status_code == 200
    assert str(machine_model.id) in {row["id"] for row in response.json()}


async def test_revoked_machine_is_not_listed(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    owner_machine, _ = machine
    created = await client.post(
        "/api/v1/machines",
        headers=admin_auth_headers,
        json={"owner_user_id": str(owner_machine.owner_user_id), "display_name": "to-revoke"},
    )
    new_id = created.json()["id"]

    before = await client.get("/api/v1/machines", headers=admin_auth_headers)
    assert new_id in {row["id"] for row in before.json()}

    revoked = await client.post(f"/api/v1/machines/{new_id}/revoke", headers=admin_auth_headers)
    assert revoked.status_code == 200

    after = await client.get("/api/v1/machines", headers=admin_auth_headers)
    assert new_id not in {row["id"] for row in after.json()}
