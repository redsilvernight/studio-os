from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.project import ProjectModel


async def test_project_state_lists_active_tasks_and_claims(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    task = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Active task"},
    )
    completed_task = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Done task"},
    )
    await client.patch(
        f"/api/v1/tasks/{completed_task.json()['id']}",
        headers={**auth_headers, "If-Match-Version": "1"},
        json={"status": "completed"},
    )
    await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "docs/design.md",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )

    state = await client.get(f"/api/v1/projects/{project.id}/state", headers=auth_headers)
    assert state.status_code == 200
    body = state.json()
    assert [t["id"] for t in body["active_tasks"]] == [task.json()["id"]]
    assert len(body["active_claims"]) == 1


async def test_unknown_project_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404
