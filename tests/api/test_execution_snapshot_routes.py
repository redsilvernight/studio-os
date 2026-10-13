"""P04-snapshot-capture: the machine posts the launch's execution snapshot over
the outbox; a replay returns the stored row, a different body is refused, and
a payload carrying secret material is never stored."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models import ExecutionSnapshotModel
from studio_api.db.models.machine import MachineModel
from studio_contracts.execution_snapshot import digest_of

from tests.api.test_task_launches import _caps, _heartbeat, _launch, _ready_target

CANARY = "sk-canary0123456789abcdefXYZ"


def _body(**applied: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "capture_status": "partial",
        "resolution": None,
        "applied": {
            "harness_id": "claude-code",
            "harness_version": "2.1.0",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "worktree_branch": "task/abcd1234-demo",
            "local_policy_digest": digest_of({"opt_in": True}),
            "access_mode": "workspace_write",
            **applied,
        },
        "capture_errors": [
            {
                "code": "resolution_unavailable",
                "field": "resolution",
                "detail": "no_agent_definition",
            }
        ],
    }


async def _created_launch(
    client: AsyncClient, headers: dict[str, str], machine: tuple[MachineModel, str]
) -> dict[str, Any]:
    project_id, task_id, machine_id = await _ready_target(client, headers, machine)
    response = await _launch(client, headers, project_id, task_id, machine_id)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _count(session: AsyncSession, launch_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ExecutionSnapshotModel)
        .where(ExecutionSnapshotModel.task_launch_id == launch_id)
    )
    return int(result.scalar_one())


async def test_post_then_replay_returns_the_same_snapshot(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    launch = await _created_launch(client, auth_headers, machine)
    url = f"/api/v1/task-launches/{launch['id']}/snapshot"

    assert (await client.get(url, headers=auth_headers)).status_code == 404
    first = await client.post(url, json=_body(), headers=auth_headers)
    assert first.status_code == 201, first.text
    replay = await client.post(url, json=_body(), headers=auth_headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["content_hash"] == first.json()["content_hash"]
    assert await _count(db_session, launch["id"]) == 1

    read = await client.get(url, headers=auth_headers)
    assert read.status_code == 200
    assert read.json()["payload"]["applied"]["git_sha"] == "a" * 40


async def test_different_content_is_refused_as_immutable(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    launch = await _created_launch(client, auth_headers, machine)
    url = f"/api/v1/task-launches/{launch['id']}/snapshot"
    assert (await client.post(url, json=_body(), headers=auth_headers)).status_code == 201
    other = await client.post(url, json=_body(git_sha="b" * 40), headers=auth_headers)
    assert other.status_code == 409
    assert other.json()["detail"]["error_code"] == "execution_snapshot_immutable"


async def test_other_machine_cannot_post(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    other_auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    launch = await _created_launch(client, auth_headers, machine)
    other_model, _ = other_machine
    await _heartbeat(client, other_auth_headers, str(other_model.id), _caps(launch["project_id"]))
    response = await client.post(
        f"/api/v1/task-launches/{launch['id']}/snapshot", json=_body(), headers=other_auth_headers
    )
    assert response.status_code == 403


async def test_unknown_launch_is_404(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    url = "/api/v1/task-launches/00000000-0000-4000-8000-000000000000/snapshot"
    assert (await client.post(url, json=_body(), headers=auth_headers)).status_code == 404


async def test_canary_secret_is_rejected_and_never_stored(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    launch = await _created_launch(client, auth_headers, machine)
    url = f"/api/v1/task-launches/{launch['id']}/snapshot"
    response = await client.post(url, json=_body(harness_version=CANARY), headers=auth_headers)
    assert response.status_code == 422
    assert await _count(db_session, launch["id"]) == 0
    path = await client.post(
        url, json=_body(worktree_branch="C:\\Users\\me\\repo"), headers=auth_headers
    )
    assert path.status_code == 422
    assert await _count(db_session, launch["id"]) == 0
