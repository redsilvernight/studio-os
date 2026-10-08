from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.vault import VaultNoteVersionModel


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create_note(
    client: AsyncClient, headers: dict[str, str], project_id: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "scope": "project" if project_id is not None else "studio",
        "slug": _slug("idem"),
        "title": "A title",
        "body": "A body",
    }
    if project_id is not None:
        payload["project_id"] = project_id
    response = await client.post("/api/v1/vault/notes", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _versions(db_session: AsyncSession, note_id: str) -> list[int]:
    rows = (
        (
            await db_session.execute(
                select(VaultNoteVersionModel).where(
                    VaultNoteVersionModel.note_id == uuid.UUID(note_id)
                )
            )
        )
        .scalars()
        .all()
    )
    return sorted(row.version for row in rows)


async def test_patch_replays_without_a_new_version(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    note = await _create_note(client, auth_headers, str(project.id))
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    body = {"expected_version": 1, "title": "Renamed"}

    first = await client.patch(f"/api/v1/vault/notes/{note['id']}", headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 2
    assert first.json()["title"] == "Renamed"

    replay = await client.patch(f"/api/v1/vault/notes/{note['id']}", headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    assert await _versions(db_session, str(note["id"])) == [1, 2]

    fetched = await client.get(f"/api/v1/vault/notes/{note['id']}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["version"] == 2


async def test_patch_without_key_keeps_version_guard(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create_note(client, auth_headers, str(project.id))
    url = f"/api/v1/vault/notes/{note['id']}"

    first = await client.patch(
        url, headers=auth_headers, json={"expected_version": 1, "title": "First"}
    )
    assert first.status_code == 200
    assert first.json()["version"] == 2

    stale = await client.patch(
        url, headers=auth_headers, json={"expected_version": 1, "title": "Second"}
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["error_code"] == "version_conflict"
    assert stale.json()["detail"]["server_version"] == 2


async def test_patch_same_key_different_body_is_409(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create_note(client, auth_headers, str(project.id))
    url = f"/api/v1/vault/notes/{note['id']}"
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}

    first = await client.patch(url, headers=headers, json={"expected_version": 1, "title": "First"})
    assert first.status_code == 200, first.text

    mismatch = await client.patch(
        url, headers=headers, json={"expected_version": 2, "title": "Other"}
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"

    unchanged = await client.get(url, headers=auth_headers)
    assert unchanged.json()["title"] == "First"
    assert unchanged.json()["version"] == 2


@pytest.mark.isolation
async def test_patch_replay_by_an_outsider_is_403_not_the_note(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    project = (
        await client.post(
            "/api/v1/projects", headers=auth_headers, json={"slug": _slug("iso"), "name": "Iso"}
        )
    ).json()
    note = await _create_note(client, auth_headers, project["id"])
    url = f"/api/v1/vault/notes/{note['id']}"
    key = str(uuid.uuid4())
    body = {"expected_version": 1, "title": "Owner edit"}

    first = await client.patch(url, headers={**auth_headers, "Idempotency-Key": key}, json=body)
    assert first.status_code == 200, first.text

    replay = await client.patch(
        url, headers={**other_auth_headers, "Idempotency-Key": key}, json=body
    )
    assert replay.status_code == 403
    assert replay.json()["detail"]["resource"] == "project"
    assert "title" not in replay.json()


async def test_patch_key_is_scoped_per_note(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    key = str(uuid.uuid4())
    first_note = await _create_note(client, auth_headers, str(project.id))
    second_note = await _create_note(client, auth_headers, str(project.id))

    headers = {**auth_headers, "Idempotency-Key": key}
    first = await client.patch(
        f"/api/v1/vault/notes/{first_note['id']}",
        headers=headers,
        json={"expected_version": 1, "title": "One"},
    )
    assert first.status_code == 200, first.text

    second = await client.patch(
        f"/api/v1/vault/notes/{second_note['id']}",
        headers=headers,
        json={"expected_version": 1, "title": "Two"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == second_note["id"]
    assert second.json()["title"] == "Two"
