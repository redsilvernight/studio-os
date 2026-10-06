from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.vault import VaultNoteVersionModel


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _note_payload(
    scope: str, slug: str, project_id: str | None = None, **overrides: object
) -> dict[str, object]:
    payload: dict[str, object] = {
        "scope": scope,
        "slug": slug,
        "title": "A title",
        "body": "A body",
        **({"project_id": project_id} if project_id is not None else {}),
    }
    payload.update(overrides)
    return payload


async def _create(
    client: AsyncClient, headers: dict[str, str], payload: dict[str, object]
) -> dict[str, object]:
    response = await client.post("/api/v1/vault/notes", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_and_get_note(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    note = await _create(
        client, auth_headers, _note_payload("project", _slug("n"), str(project.id))
    )
    assert note["version"] == 1
    assert note["status"] == "draft"
    assert note["scope"] == "project"
    assert note["project_id"] == str(project.id)
    assert len(note["content_hash"]) == 64
    assert note["author_type"] == "user"
    assert note["author_id"] == str(machine_model.owner_user_id)
    assert note["readable_id"] is None

    fetched = await client.get(f"/api/v1/vault/notes/{note['id']}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == note["id"]
    assert fetched.json()["body"] == "A body"


async def test_decision_note_gets_a_readable_id(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    note = await _create(
        client,
        auth_headers,
        _note_payload("studio", _slug("d"), note_type="decision", status="proposed"),
    )
    assert note["note_type"] == "decision"
    assert note["readable_id"].startswith("DEC-")  # type: ignore[union-attr]


async def test_create_note_idempotency_key_replays(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    payload = _note_payload("project", _slug("r"), str(project.id))
    first = await client.post("/api/v1/vault/notes", headers=headers, json=payload)
    second = await client.post("/api/v1/vault/notes", headers=headers, json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listing = await client.get(
        "/api/v1/vault/tree", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len([i for i in listing.json()["items"] if i["slug"] == payload["slug"]]) == 1


async def test_update_note_and_version_history(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create(
        client, auth_headers, _note_payload("project", _slug("u"), str(project.id))
    )

    updated = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=auth_headers,
        json={"expected_version": 1, "title": "Renamed"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["title"] == "Renamed"

    versions = await client.get(f"/api/v1/vault/notes/{note['id']}/versions", headers=auth_headers)
    page = versions.json()
    assert [v["version"] for v in page["items"]] == [1, 2]
    assert page["items"][0]["title"] == "A title"
    assert page["items"][1]["title"] == "Renamed"


async def test_update_note_stale_version_is_409(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create(
        client, auth_headers, _note_payload("project", _slug("s"), str(project.id))
    )
    await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=auth_headers,
        json={"expected_version": 1, "title": "First"},
    )
    stale = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=auth_headers,
        json={"expected_version": 1, "title": "Stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["error_code"] == "version_conflict"
    assert stale.json()["detail"]["server_version"] == 2


async def test_single_version_read(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create(
        client, auth_headers, _note_payload("project", _slug("v"), str(project.id))
    )
    version = await client.get(f"/api/v1/vault/notes/{note['id']}/versions/1", headers=auth_headers)
    assert version.status_code == 200
    assert version.json()["version"] == 1
    assert version.json()["title"] == "A title"


async def test_slug_conflict_is_409(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    slug = _slug("c")
    await _create(client, auth_headers, _note_payload("project", slug, str(project.id)))
    conflict = await client.post(
        "/api/v1/vault/notes",
        headers=auth_headers,
        json=_note_payload("project", slug, str(project.id)),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error_code"] == "vault_slug_conflict"


async def test_link_to_unreadable_note_is_422(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    target = await _create(
        client, auth_headers, _note_payload("project", _slug("t"), str(project.id))
    )
    response = await client.post(
        "/api/v1/vault/notes",
        headers=auth_headers,
        json=_note_payload(
            "project",
            _slug("l"),
            str(project.id),
            links=[{"target_note_id": str(uuid.uuid4()), "kind": "links_to"}],
        ),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_vault_link"

    ok = await client.post(
        "/api/v1/vault/notes",
        headers=auth_headers,
        json=_note_payload(
            "project",
            _slug("l2"),
            str(project.id),
            links=[{"target_note_id": target["id"], "kind": "links_to"}],
        ),
    )
    assert ok.status_code == 201
    assert ok.json()["links"][0]["target_note_id"] == target["id"]


async def test_tree_is_paginated_by_slug(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    slugs = sorted(_slug("tree") for _ in range(5))
    for slug in slugs:
        await _create(client, auth_headers, _note_payload("studio", slug))

    first = await client.get(
        "/api/v1/vault/tree", headers=auth_headers, params={"scope": "studio", "limit": 2}
    )
    page1 = first.json()
    assert [i["slug"] for i in page1["items"]] == slugs[:2]
    assert page1["next_cursor"] is not None

    second = await client.get(
        "/api/v1/vault/tree",
        headers=auth_headers,
        params={"scope": "studio", "limit": 2, "cursor": page1["next_cursor"]},
    )
    page2 = second.json()
    assert [i["slug"] for i in page2["items"]] == slugs[2:4]
    assert page2["next_cursor"] is not None

    third = await client.get(
        "/api/v1/vault/tree",
        headers=auth_headers,
        params={"scope": "studio", "limit": 2, "cursor": page2["next_cursor"]},
    )
    page3 = third.json()
    assert [i["slug"] for i in page3["items"]] == slugs[4:]
    assert page3["next_cursor"] is None


async def test_studio_validated_status_is_admin_only(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
) -> None:
    note = await _create(client, auth_headers, _note_payload("studio", _slug("w")))

    forbidden = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=auth_headers,
        json={"expected_version": 1, "status": "validated"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["error_code"] == "forbidden"

    allowed = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=admin_auth_headers,
        json={"expected_version": 1, "status": "validated"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "validated"


@pytest.mark.isolation
async def test_non_member_gets_403_on_project_note(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    project = (
        await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json={"slug": _slug("iso"), "name": "Iso"},
        )
    ).json()
    note = await _create(client, auth_headers, _note_payload("project", _slug("p"), project["id"]))

    read = await client.get(f"/api/v1/vault/notes/{note['id']}", headers=other_auth_headers)
    assert read.status_code == 403
    assert read.json()["detail"]["resource"] == "project"

    write = await client.post(
        "/api/v1/vault/notes",
        headers=other_auth_headers,
        json=_note_payload("project", _slug("q"), project["id"]),
    )
    assert write.status_code == 403

    tree = await client.get(
        "/api/v1/vault/tree", headers=other_auth_headers, params={"project_id": project["id"]}
    )
    assert tree.status_code == 403


async def test_each_write_appends_exactly_one_version(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    note = await _create(
        client, auth_headers, _note_payload("project", _slug("h"), str(project.id))
    )
    for i in range(3):
        response = await client.patch(
            f"/api/v1/vault/notes/{note['id']}",
            headers=auth_headers,
            json={"expected_version": i + 1, "title": f"T{i}"},
        )
        assert response.status_code == 200

    rows = (
        (
            await db_session.execute(
                select(VaultNoteVersionModel).where(
                    VaultNoteVersionModel.note_id == uuid.UUID(note["id"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert [r.version for r in rows] == [1, 2, 3, 4]
