from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel
from studio_api.services.heartbeats import derive_status
from studio_api.settings import Settings


async def test_heartbeat_reports_online(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    response = await client.post(
        "/api/v1/heartbeats",
        headers=auth_headers,
        json={
            "machine_id": str(machine_model.id),
            "client_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "online"
    assert body["machine_id"] == str(machine_model.id)


async def test_heartbeat_rejects_body_machine_id_different_from_authenticated_machine(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/heartbeats",
        headers=auth_headers,
        json={
            "machine_id": str(uuid.uuid4()),
            "client_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "machine_id_mismatch"


def test_derive_status_thresholds() -> None:
    settings = Settings(heartbeat_interval_seconds=30, heartbeat_offline_after_seconds=90)

    never_seen = MachineModel(display_name="m", credential_hash="h")
    assert derive_status(never_seen, settings) == "offline"

    online = MachineModel(display_name="m", credential_hash="h")
    online.last_seen_at = datetime.now(UTC) - timedelta(seconds=10)
    assert derive_status(online, settings) == "online"

    idle = MachineModel(display_name="m", credential_hash="h")
    idle.last_seen_at = datetime.now(UTC) - timedelta(seconds=60)
    assert derive_status(idle, settings) == "idle"

    offline = MachineModel(display_name="m", credential_hash="h")
    offline.last_seen_at = datetime.now(UTC) - timedelta(seconds=200)
    assert derive_status(offline, settings) == "offline"
