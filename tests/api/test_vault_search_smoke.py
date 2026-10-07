from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.project import ProjectModel


async def test_search_smoke(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    pid = str(project.id)
    task = str(uuid.uuid4())
    base = {"scope": "project", "project_id": pid}
    anchored = await client.post(
        "/api/v1/vault/notes",
        headers=auth_headers,
        json={
            **base,
            "slug": f"a-{uuid.uuid4().hex[:8]}",
            "title": "Convention de nommage",
            "body": "Rien de lexical ici.",
            "anchors": ["path:services/api/", f"task:{task}"],
        },
    )
    assert anchored.status_code == 201, anchored.text
    lexical = await client.post(
        "/api/v1/vault/notes",
        headers=auth_headers,
        json={
            **base,
            "slug": f"l-{uuid.uuid4().hex[:8]}",
            "title": "Quotas des transferts",
            "body": "Le quota des transferts est vérifié avant signature. " * 20,
        },
    )
    assert lexical.status_code == 201, lexical.text

    response = await client.get(
        "/api/v1/vault/search",
        headers=auth_headers,
        params={
            "q": "quota transferts",
            "project_id": pid,
            "path": ["services/api/src/x.py", "docs/"],
            "task_id": task,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    reasons = [(hit["note"]["title"], hit["reason"]) for hit in body["items"]]
    assert reasons[0] == ("Convention de nommage", "anchor"), reasons
    assert ("Quotas des transferts", "lexical") in reasons
    assert body["items"][0]["matched_anchors"] == ["path:services/api/", f"task:{task}"]
    assert all(len(hit["snippet"]) <= 280 for hit in body["items"])
