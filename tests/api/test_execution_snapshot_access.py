"""P04-provenance-ui: the execution snapshot — the launch's redacted export —
is readable only by members of the launch's project."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel

from tests.api.test_execution_snapshot_routes import _body, _created_launch

pytestmark = pytest.mark.isolation


async def test_snapshot_export_is_refused_to_a_non_member(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    launch = await _created_launch(client, auth_headers, machine)
    url = f"/api/v1/task-launches/{launch['id']}/snapshot"
    assert (await client.post(url, json=_body(), headers=auth_headers)).status_code == 201

    denied = await client.get(url, headers=other_auth_headers)
    assert denied.status_code == 403, denied.text
    assert "payload" not in denied.text
