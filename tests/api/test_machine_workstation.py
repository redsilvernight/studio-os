"""DEC-0226: tool machines attach to their physical workstation, one level,
same owner; credentials and isolation are untouched."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create(client: AsyncClient, headers: dict[str, str], **body: str) -> dict:
    response = await client.post(
        "/api/v1/machines", headers=headers, json={"display_name": "FLO-LAPTOP", **body}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_tool_machine_attaches_to_its_workstation_and_keeps_its_own_credential(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    desktop = await _create(client, auth_headers)
    assert desktop["workstation_id"] is None
    tool = await _create(
        client,
        _bearer(desktop["credential"]),
        display_name="FLO-LAPTOP · Codex",
        workstation_id=desktop["id"],
    )
    assert tool["workstation_id"] == desktop["id"]
    assert tool["credential"] != desktop["credential"]
    me = await client.get("/api/v1/machines/me", headers=_bearer(tool["credential"]))
    assert me.json()["id"] == tool["id"]
    listed = await client.get("/api/v1/machines", headers=auth_headers)
    by_id = {m["id"]: m for m in listed.json()}
    assert by_id[tool["id"]]["workstation_id"] == desktop["id"]

    adopted = await client.post(f"/api/v1/machines/{tool['id']}/adopt", headers=auth_headers)
    assert adopted.status_code == 200
    assert adopted.json()["id"] == tool["id"]
    assert adopted.json()["workstation_id"] == desktop["id"]


async def test_a_foreign_or_missing_workstation_is_404_and_an_invalid_one_409(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    for foreign in (other_machine[0].id, uuid.uuid4()):
        response = await client.post(
            "/api/v1/machines",
            headers=auth_headers,
            json={"display_name": "hijack", "workstation_id": str(foreign)},
        )
        assert response.status_code == 404

    desktop = await _create(client, auth_headers)
    tool = await _create(client, auth_headers, workstation_id=desktop["id"])
    nested = await client.post(
        "/api/v1/machines",
        headers=auth_headers,
        json={"display_name": "nested", "workstation_id": tool["id"]},
    )
    assert nested.status_code == 409
    assert nested.json()["detail"]["error_code"] == "workstation_invalid"

    await client.post(f"/api/v1/machines/{desktop['id']}/revoke", headers=auth_headers)
    revoked = await client.post(
        "/api/v1/machines",
        headers=auth_headers,
        json={"display_name": "late", "workstation_id": desktop["id"]},
    )
    assert revoked.status_code == 409


async def test_attach_and_detach_an_existing_machine(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    desktop = await _create(client, auth_headers)
    legacy = await _create(client, auth_headers, display_name="FLO-LAPTOP · Claude Code")
    url = f"/api/v1/machines/{legacy['id']}/workstation"

    missing_version = await client.put(
        url, headers=auth_headers, json={"workstation_id": desktop["id"]}
    )
    assert missing_version.status_code == 422
    stale = await client.put(
        url,
        headers={**auth_headers, "If-Match-Version": str(legacy["version"] + 5)},
        json={"workstation_id": desktop["id"]},
    )
    assert stale.status_code == 409

    attached = await client.put(
        url,
        headers={**auth_headers, "If-Match-Version": str(legacy["version"])},
        json={"workstation_id": desktop["id"]},
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["workstation_id"] == desktop["id"]
    me = await client.get("/api/v1/machines/me", headers=_bearer(legacy["credential"]))
    assert me.status_code == 200

    self_attach = await client.put(
        f"/api/v1/machines/{desktop['id']}/workstation",
        headers={**auth_headers, "If-Match-Version": str(desktop["version"])},
        json={"workstation_id": legacy["id"]},
    )
    assert self_attach.status_code == 409

    detached = await client.put(
        url,
        headers={**auth_headers, "If-Match-Version": str(attached.json()["version"])},
        json={"workstation_id": None},
    )
    assert detached.status_code == 200
    assert detached.json()["workstation_id"] is None


async def test_workstation_change_hides_foreign_machines_and_refuses_agents(
    client: AsyncClient,
    auth_headers: dict[str, str],
    agent_auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    desktop = await _create(client, auth_headers)
    foreign = await client.put(
        f"/api/v1/machines/{other_machine[0].id}/workstation",
        headers={**auth_headers, "If-Match-Version": "1"},
        json={"workstation_id": desktop["id"]},
    )
    assert foreign.status_code == 404

    mine = await _create(client, auth_headers)
    onto_foreign = await client.put(
        f"/api/v1/machines/{mine['id']}/workstation",
        headers={**auth_headers, "If-Match-Version": str(mine["version"])},
        json={"workstation_id": str(other_machine[0].id)},
    )
    assert onto_foreign.status_code == 404

    agent = await client.put(
        f"/api/v1/machines/{mine['id']}/workstation",
        headers={**agent_auth_headers, "If-Match-Version": str(mine["version"])},
        json={"workstation_id": desktop["id"]},
    )
    assert agent.status_code == 403
