from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from studio_api.db.models.project import ProjectModel

SNIPPET_MAX = 280


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    scope: str = "project",
    project_id: uuid.UUID | None = None,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "scope": scope,
        "slug": _slug("s"),
        "title": "Titre",
        "body": "Corps",
        **overrides,
    }
    if project_id is not None:
        payload["project_id"] = str(project_id)
    response = await client.post("/api/v1/vault/notes", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _set_status(
    client: AsyncClient, headers: dict[str, str], note: dict[str, object], status: str
) -> dict[str, object]:
    response = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=headers,
        json={"expected_version": note["version"], "status": status},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _search(
    client: AsyncClient, headers: dict[str, str], **params: object
) -> dict[str, object]:
    response = await client.get("/api/v1/vault/search", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _labelled(body: dict[str, object]) -> list[tuple[str, str]]:
    items = body["items"]
    assert isinstance(items, list)
    return [(hit["note"]["title"], hit["reason"]) for hit in items]


def _titles(body: dict[str, object]) -> list[str]:
    items = body["items"]
    assert isinstance(items, list)
    return [hit["note"]["title"] for hit in items]


async def test_missing_criteria_is_422(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/api/v1/vault/search", headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "missing_search_criteria"


async def test_scope_filter(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    anchor = "path:scope/"
    studio = await _create(
        client, auth_headers, scope="studio", title="Périmètre studio", anchors=[anchor]
    )
    project_note = await _create(
        client,
        auth_headers,
        scope="project",
        project_id=project.id,
        title="Périmètre projet",
        anchors=[anchor],
    )

    both = await _search(client, auth_headers, project_id=str(project.id), path="scope/")
    assert set(_titles(both)) == {studio["title"], project_note["title"]}

    only_studio = await _search(client, auth_headers, scope="studio", path="scope/")
    assert _titles(only_studio) == [studio["title"]]

    only_project = await _search(
        client, auth_headers, scope="project", project_id=str(project.id), path="scope/"
    )
    assert _titles(only_project) == [project_note["title"]]


async def test_note_type_filter(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    anchor = "path:type/"
    rule = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Une règle",
        note_type="rule",
        anchors=[anchor],
    )
    lesson = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Une leçon",
        note_type="lesson",
        anchors=[anchor],
    )

    rules = await _search(
        client, auth_headers, project_id=str(project.id), path="type/", note_type=["rule"]
    )
    assert _titles(rules) == [rule["title"]]

    lessons = await _search(
        client, auth_headers, project_id=str(project.id), path="type/", note_type=["lesson"]
    )
    assert _titles(lessons) == [lesson["title"]]


async def test_status_filter(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    anchor = "path:st/"
    draft = await _create(
        client, auth_headers, project_id=project.id, title="Brouillon", anchors=[anchor]
    )
    superseded = await _create(
        client, auth_headers, project_id=project.id, title="Remplacée", anchors=[anchor]
    )
    superseded = await _set_status(client, auth_headers, superseded, "superseded")

    explicit = await _search(
        client, auth_headers, project_id=str(project.id), path="st/", status=["superseded"]
    )
    assert _titles(explicit) == [superseded["title"]]

    default = await _search(client, auth_headers, project_id=str(project.id), path="st/")
    assert _titles(default) == [draft["title"]]


async def test_superseded_hidden_by_default_and_opt_in(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Note remplacée",
        anchors=["path:sup/"],
    )
    await _set_status(client, auth_headers, note, "superseded")

    hidden = await _search(client, auth_headers, project_id=str(project.id), path="sup/")
    assert hidden["items"] == []
    assert hidden["total"] == 0

    included = await _search(
        client,
        auth_headers,
        project_id=str(project.id),
        path="sup/",
        include_superseded="true",
    )
    assert _titles(included) == ["Note remplacée"]


async def test_archived_hidden_unless_explicit_status(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Note archivée",
        anchors=["path:arch/"],
    )
    await _set_status(client, auth_headers, note, "archived")

    for params in ({}, {"include_superseded": "true"}):
        body = await _search(
            client, auth_headers, project_id=str(project.id), path="arch/", **params
        )
        assert body["items"] == [], params

    explicit = await _search(
        client, auth_headers, project_id=str(project.id), path="arch/", status=["archived"]
    )
    assert _titles(explicit) == ["Note archivée"]


async def test_ranking_anchor_then_linked_then_lexical(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    task = str(uuid.uuid4())
    anchored = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Ancrée",
        body="Rien de lexical ici.",
        anchors=["path:services/api/", f"task:{task}"],
    )
    linked = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Liée",
        body="Rien de lexical ici non plus.",
        links=[{"target_note_id": str(anchored["id"]), "kind": "links_to"}],
    )
    await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Quotas des transferts",
        body="Le quota des transferts est vérifié avant signature. " * 20,
    )

    body = await _search(
        client,
        auth_headers,
        project_id=str(project.id),
        q="quota transferts",
        path=["services/api/src/x.py"],
        task_id=task,
    )
    assert _labelled(body) == [
        ("Ancrée", "anchor"),
        ("Liée", "linked"),
        ("Quotas des transferts", "lexical"),
    ]
    top = body["items"][0]
    assert top["matched_anchors"] == ["path:services/api/", f"task:{task}"]
    assert body["items"][1]["note"]["id"] == linked["id"]


async def test_enclosing_directory_anchor_matches_nested_path(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Convention API",
        body="Rien de lexical.",
        anchors=["path:services/api/"],
    )

    body = await _search(
        client, auth_headers, project_id=str(project.id), path="services/api/src/x.py"
    )
    assert _titles(body) == [note["title"]]
    assert body["items"][0]["reason"] == "anchor"
    assert body["items"][0]["matched_anchors"] == ["path:services/api/"]


async def test_task_id_anchor_matches(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    task = str(uuid.uuid4())
    note = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Lié à la tâche",
        body="Rien de lexical.",
        anchors=[f"task:{task}"],
    )

    body = await _search(client, auth_headers, project_id=str(project.id), task_id=task)
    assert _titles(body) == [note["title"]]
    assert body["items"][0]["matched_anchors"] == [f"task:{task}"]


@pytest.mark.isolation
async def test_outsider_gets_403(
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

    response = await client.get(
        "/api/v1/vault/search",
        headers=other_auth_headers,
        params={"project_id": project["id"], "q": "vault"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["resource"] == "project"


async def test_snippets_are_bounded_and_body_never_returned(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Quota transferts",
        body="Le quota des transferts est vérifié avant signature. " * 60,
    )

    body = await _search(client, auth_headers, project_id=str(project.id), q="quota transferts")
    assert body["items"]
    for hit in body["items"]:
        assert 0 < len(hit["snippet"]) <= SNIPPET_MAX
        assert "body" not in hit["note"]


async def test_low_max_chars_truncates(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    for i in range(4):
        await _create(
            client,
            auth_headers,
            project_id=project.id,
            title=f"quota transferts {i} " + "x" * 175,
            body="quota transferts " * 40,
        )

    body = await _search(
        client, auth_headers, project_id=str(project.id), q="quota transferts", max_chars=500
    )
    assert body["truncated"] is True
    assert body["total"] == 4
    assert len(body["items"]) < body["total"]


async def test_anchor_update_replaces_anchors(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Note déplacée",
        body="Rien de lexical.",
        anchors=["path:services/api/"],
    )

    before = await _search(
        client, auth_headers, project_id=str(project.id), path="services/api/src/x.py"
    )
    assert _titles(before) == [note["title"]]

    updated = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=auth_headers,
        json={"expected_version": 1, "anchors": ["path:docs/"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["anchors"] == ["path:docs/"]
    assert updated.json()["content_hash"] != note["content_hash"]

    stale = await _search(
        client, auth_headers, project_id=str(project.id), path="services/api/src/x.py"
    )
    assert stale["items"] == []

    moved = await _search(client, auth_headers, project_id=str(project.id), path="docs/readme.md")
    assert _titles(moved) == [note["title"]]
    assert moved["items"][0]["matched_anchors"] == ["path:docs/"]


async def test_empty_anchors_keep_content_hash(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    note = await _create(
        client,
        auth_headers,
        project_id=project.id,
        title="Sans ancre",
        body="Un corps stable.",
    )

    updated = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=auth_headers,
        json={"expected_version": 1, "anchors": []},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["anchors"] == []
    assert updated.json()["content_hash"] == note["content_hash"]
