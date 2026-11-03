"""P04-replay-option: read-only replay preview of a terminal attempt against its
execution snapshot, and a retry that confirms it records the accepted basis
without touching the source snapshot."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models import ExecutionSnapshotModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel

from tests.api.test_execution_snapshot_routes import _body
from tests.api.test_task_launch_recovery import _failed_launch, _retry
from tests.api.test_task_launches import _launch, _ready_target


def _resolution(resource_id: str) -> dict[str, Any]:
    return {
        "agent_stable_key": "builder",
        "resources": [
            {
                "role": "agent",
                "resource_id": resource_id,
                "kind": "agent_definition",
                "stable_key": "builder",
                "scope": "project",
                "version": 3,
                "version_origin": "active",
                "content_digest": "sha256:" + "b" * 64,
            }
        ],
    }


async def _snapshot(
    client: AsyncClient, headers: dict[str, str], launch_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/task-launches/{launch_id}/snapshot", json=body, headers=headers
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _preview(client: AsyncClient, headers: dict[str, str], launch_id: str) -> Any:
    return await client.get(f"/api/v1/task-launches/{launch_id}/replay-preview", headers=headers)


def _codes(preview: dict[str, Any]) -> set[str]:
    return {item["code"] for item in preview["limitations"]}


async def _replay(
    client: AsyncClient, headers: dict[str, str], launch_id: str, preview: dict[str, Any]
) -> Any:
    return await client.post(
        f"/api/v1/task-launches/{launch_id}/retry",
        json={
            "replay": {
                "snapshot_content_hash": preview["snapshot_content_hash"],
                "preview_digest": preview["preview_digest"],
            }
        },
        headers=headers,
    )


async def _launch_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(TaskLaunchModel))
    return int(result.scalar_one())


async def test_preview_without_snapshot_is_refused_and_creates_nothing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    _, launch = await _failed_launch(client, auth_headers, machine)
    before = await _launch_count(db_session)

    response = await _preview(client, auth_headers, launch["id"])

    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["verdict"] == "refused"
    assert preview["snapshot_id"] is None
    assert "snapshot_missing" in _codes(preview)
    assert await _launch_count(db_session) == before


async def test_preview_of_a_running_attempt_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    await _snapshot(client, auth_headers, launch["id"], _body())

    preview = (await _preview(client, auth_headers, launch["id"])).json()

    assert preview["verdict"] == "refused"
    assert "launch_not_terminal" in _codes(preview)


async def test_preview_is_limited_and_stable_for_the_same_sources(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    _, launch = await _failed_launch(client, auth_headers, machine)
    snapshot = await _snapshot(client, auth_headers, launch["id"], _body(git_dirty=True))

    first = (await _preview(client, auth_headers, launch["id"])).json()
    second = (await _preview(client, auth_headers, launch["id"])).json()

    assert first["verdict"] == "limited"
    assert first["snapshot_content_hash"] == snapshot["content_hash"]
    assert {
        "source_worktree_dirty",
        "resolution_unrecorded",
        "git_state_not_pinned",
        "output_not_reproducible",
    } <= _codes(first)
    assert all(item["severity"] == "limitation" for item in first["limitations"])
    assert first["preview_digest"] == second["preview_digest"]


async def test_missing_library_version_is_an_explicit_substitution(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    _, launch = await _failed_launch(client, auth_headers, machine)
    body = {**_body(), "capture_status": "ok", "capture_errors": []}
    body["resolution"] = _resolution(str(uuid.uuid4()))
    await _snapshot(client, auth_headers, launch["id"], body)

    preview = (await _preview(client, auth_headers, launch["id"])).json()

    assert preview["verdict"] == "limited"
    assert "library_version_unavailable" in _codes(preview)
    resource = next(d for d in preview["differences"] if d["subject_kind"] == "resource")
    assert resource["change"] == "unavailable"
    assert resource["recorded"].startswith("v3 sha256:")


async def test_preview_by_another_user_is_not_a_replay(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    _, launch = await _failed_launch(client, auth_headers, machine)
    await _snapshot(client, auth_headers, launch["id"], _body())

    response = await _preview(client, other_auth_headers, launch["id"])

    if response.status_code == 200:
        preview = response.json()
        assert preview["verdict"] == "refused"
        assert "not_authorized" in _codes(preview)
    else:
        assert response.status_code in {403, 404}, response.text


async def test_stale_confirmation_creates_no_attempt(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    _, launch = await _failed_launch(client, auth_headers, machine)
    await _snapshot(client, auth_headers, launch["id"], _body())
    preview = (await _preview(client, auth_headers, launch["id"])).json()
    before = await _launch_count(db_session)

    stale = {**preview, "preview_digest": "sha256:" + "0" * 64}
    response = await _replay(client, auth_headers, launch["id"], stale)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "replay_preview_stale"
    assert detail["preview_digest"] == preview["preview_digest"]
    assert await _launch_count(db_session) == before


async def test_refused_preview_cannot_be_confirmed(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    _, launch = await _failed_launch(client, auth_headers, machine)
    fake = {
        "snapshot_content_hash": "sha256:" + "1" * 64,
        "preview_digest": "sha256:" + "2" * 64,
    }

    response = await _replay(client, auth_headers, launch["id"], fake)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "replay_refused"
    assert "snapshot_missing" in detail["codes"]


async def test_confirmed_replay_records_the_basis_and_keeps_the_snapshot(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    _, launch = await _failed_launch(client, auth_headers, machine)
    snapshot = await _snapshot(client, auth_headers, launch["id"], _body(git_dirty=True))
    preview = (await _preview(client, auth_headers, launch["id"])).json()

    response = await _replay(client, auth_headers, launch["id"], preview)

    assert response.status_code == 201, response.text
    attempt = response.json()
    assert attempt["retry_of_launch_id"] == launch["id"]
    basis = attempt["replay_basis"]
    assert basis["source_launch_id"] == launch["id"]
    assert basis["snapshot_content_hash"] == snapshot["content_hash"]
    assert basis["preview_digest"] == preview["preview_digest"]
    assert basis["verdict"] == "limited"
    assert "source_worktree_dirty" in basis["limitation_codes"]
    assert all(item["change"] != "unchanged" for item in basis["substitutions"])

    kept = await client.get(f"/api/v1/task-launches/{launch['id']}/snapshot", headers=auth_headers)
    assert kept.json()["content_hash"] == snapshot["content_hash"]
    rows = await db_session.execute(
        select(func.count())
        .select_from(ExecutionSnapshotModel)
        .where(ExecutionSnapshotModel.task_launch_id == launch["id"])
    )
    assert rows.scalar_one() == 1

    again = (await _preview(client, auth_headers, launch["id"])).json()
    assert again["verdict"] == "refused"
    assert "already_retried" in _codes(again)


async def test_plain_retry_still_has_no_replay_basis(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    _, launch = await _failed_launch(client, auth_headers, machine)

    response = await _retry(client, auth_headers, launch["id"])

    assert response.status_code == 201, response.text
    assert response.json()["replay_basis"] is None


async def test_replay_after_a_plain_retry_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    _, launch = await _failed_launch(client, auth_headers, machine)
    await _snapshot(client, auth_headers, launch["id"], _body())
    preview = (await _preview(client, auth_headers, launch["id"])).json()
    assert (await _retry(client, auth_headers, launch["id"])).status_code == 201

    response = await _replay(client, auth_headers, launch["id"], preview)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "error_code": "replay_refused",
        "codes": ["already_retried"],
    }


async def test_same_confirmation_converges_on_the_same_attempt(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, launch = await _failed_launch(client, auth_headers, machine)
    await _snapshot(client, auth_headers, launch["id"], _body())
    preview = (await _preview(client, auth_headers, launch["id"])).json()
    body = {
        "replay": {
            "snapshot_content_hash": preview["snapshot_content_hash"],
            "preview_digest": preview["preview_digest"],
        }
    }
    url = f"/api/v1/task-launches/{launch['id']}/retry"
    headers = {**auth_headers, "Idempotency-Key": f"replay-{launch['id']}"}

    first = await client.post(url, json=body, headers=headers)
    again = await client.post(url, json=body, headers=headers)
    unkeyed = await client.post(url, json=body, headers=auth_headers)

    assert first.status_code == 201, first.text
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["replay_basis"] == first.json()["replay_basis"]
    assert unkeyed.json()["id"] == first.json()["id"]

    listed = await client.get(f"/api/v1/projects/{project_id}/task-launches", headers=auth_headers)
    items = {item["id"]: item for item in listed.json()["items"]}
    assert items[first.json()["id"]]["replay_basis"] == first.json()["replay_basis"]
    assert items[launch["id"]]["replay_basis"] is None

    single = await client.get(f"/api/v1/task-launches/{first.json()['id']}", headers=auth_headers)
    assert "replay_basis" not in single.json()
