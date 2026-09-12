from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from studio_api.db.models.project import ProjectModel


async def test_create_claim_sets_ttl_and_expiry(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    before = datetime.now(UTC)
    response = await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "scenes/level_01.tscn",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    assert response.status_code == 201
    claim = response.json()
    assert claim["status"] == "active"
    expires_at = datetime.fromisoformat(claim["expires_at"])
    assert expires_at - before >= timedelta(seconds=590)


async def test_overlapping_file_claim_conflicts(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    first = await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "scenes/level_01.tscn",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    assert first.status_code == 201

    events_before = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    count_before = len(events_before.json())

    second = await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "scenes/level_01.tscn",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    assert second.status_code == 201

    events_after = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    conflict_events = [e for e in events_after.json() if e["event_type"] == "resource.conflict"]
    assert len(conflict_events) == 1
    assert len(events_after.json()) == count_before + 1


async def test_folder_claim_conflicts_with_descendant_file_claim(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "assets/",
            "resource_type": "folder",
            "ttl_seconds": 600,
        },
    )

    await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "assets/sprite.png",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )

    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    conflict_events = [e for e in events.json() if e["event_type"] == "resource.conflict"]
    assert len(conflict_events) == 1


async def test_renew_and_release_claim(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    created = await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "docs/design.md",
            "resource_type": "file",
            "ttl_seconds": 60,
        },
    )
    claim_id = created.json()["id"]
    first_expiry = created.json()["expires_at"]

    renewed = await client.post(f"/api/v1/claims/{claim_id}/renew", headers=auth_headers)
    assert renewed.status_code == 200
    assert renewed.json()["renewed_at"] is not None
    assert renewed.json()["expires_at"] >= first_expiry

    released = await client.delete(f"/api/v1/claims/{claim_id}", headers=auth_headers)
    assert released.status_code == 204

    listing = await client.get(
        "/api/v1/claims", headers=auth_headers, params={"project_id": str(project.id)}
    )
    released_claim = next(c for c in listing.json() if c["id"] == claim_id)
    assert released_claim["status"] == "released"
