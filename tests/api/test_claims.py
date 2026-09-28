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
    # The second claim itself (resource.claimed) plus the conflict it raises.
    assert len(events_after.json()) == count_before + 2


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


async def test_claim_lifecycle_emits_resource_events(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    async def resource_events() -> list[dict[str, object]]:
        response = await client.get(
            "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
        )
        return [e for e in response.json() if str(e["event_type"]).startswith("resource.")]

    created = await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "art/hero.png",
            "resource_type": "file",
            "ttl_seconds": 60,
        },
    )
    claim_id = created.json()["id"]
    await client.post(f"/api/v1/claims/{claim_id}/renew", headers=auth_headers)
    assert (
        await client.delete(f"/api/v1/claims/{claim_id}", headers=auth_headers)
    ).status_code == 204
    # Releasing twice is harmless: no second resource.released.
    assert (
        await client.delete(f"/api/v1/claims/{claim_id}", headers=auth_headers)
    ).status_code == 204

    events = await resource_events()
    types = [e["event_type"] for e in events]
    assert types.count("resource.claimed") == 1
    assert types.count("resource.renewed") == 1
    assert types.count("resource.released") == 1
    released = next(e for e in events if e["event_type"] == "resource.released")
    payload = released["payload"]
    assert isinstance(payload, dict)
    assert payload["claim_id"] == claim_id
    assert payload["resource_path"] == "art/hero.png"
    assert payload["status"] == "released"
    assert payload["previous_status"] == "active"


async def test_idempotent_claim_replay_emits_claimed_once(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    body = {
        "project_id": str(project.id),
        "resource_path": "audio/theme.ogg",
        "resource_type": "file",
        "ttl_seconds": 60,
    }
    headers = {**auth_headers, "Idempotency-Key": "claim-events-replay"}
    first = await client.post("/api/v1/claims", headers=headers, json=body)
    replay = await client.post("/api/v1/claims", headers=headers, json=body)
    assert first.json()["id"] == replay.json()["id"]
    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    claimed = [e for e in events.json() if e["event_type"] == "resource.claimed"]
    assert len(claimed) == 1
