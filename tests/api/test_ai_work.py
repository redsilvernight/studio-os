from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel


async def test_create_update_and_list_ai_work(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    created = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": str(agent.id),
            "summary": "Investigate claim TTL bug",
        },
    )
    assert created.status_code == 201
    entry = created.json()
    assert entry["status"] == "started"
    assert entry["changed_files"] == []

    updated = await client.patch(
        f"/api/v1/ai-work/{entry['id']}",
        headers=auth_headers,
        json={
            "status": "completed",
            "changed_files": ["services/api/src/studio_api/services/claims.py"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"
    assert updated.json()["changed_files"] == ["services/api/src/studio_api/services/claims.py"]

    listing = await client.get(
        "/api/v1/ai-work", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len(listing.json()) == 1


async def test_update_unknown_ai_work_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.patch(
        f"/api/v1/ai-work/{uuid.uuid4()}", headers=auth_headers, json={"status": "failed"}
    )
    assert response.status_code == 404
