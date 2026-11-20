"""Cross-studio isolation of the shared resources (DEC-0382, lot 3).

Two studios, two users: one creates in a second studio (selected with
`X-Studio-Id`), the other stays in the internal studio. Every list, single
read, creation and mutation of decisions, vault notes, library resources,
runtimes, agents, budget policies and transfers must stay inside the active
studio. A foreign id answers exactly like an unknown one, so it is compared
against a random UUID instead of hard-coding a status per resource.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.db.models.user import UserModel
from studio_api.services import provisioning as provisioning_service

pytestmark = pytest.mark.isolation
"""Real project scopes: the legacy global-scope emulation must be off, or
every fixture user would see the whole of its studio."""


def _rule_payload(scope: str = "studio") -> dict[str, Any]:
    return {
        "kind": "rule",
        "stable_key": f"iso-rule-{uuid.uuid4().hex[:10]}",
        "scope": scope,
        "title": "Isolation rule",
        "content": {
            "content_schema": "studio.library.rule/v1",
            "text": "Never cross a studio boundary.",
        },
    }


async def _second_studio(db_session: AsyncSession) -> StudioModel:
    studio = StudioModel(slug=f"iso-{uuid.uuid4().hex[:10]}", name="Isolation studio")
    db_session.add(studio)
    await db_session.flush()
    return studio


async def _project(db_session: AsyncSession, studio_id: uuid.UUID) -> ProjectModel:
    project = ProjectModel(
        slug=f"iso-proj-{uuid.uuid4().hex[:10]}", name="Isolation project", studio_id=studio_id
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _member(
    db_session: AsyncSession, studio: StudioModel | None = None, *, role: str = "admin"
) -> tuple[UserModel, MachineModel, str]:
    """A provisioned user/machine; `studio` grants an extra `owner` membership
    on top of the internal one created at provisioning time."""
    user = await provisioning_service.create_user(
        db_session, "Isolation User", f"{uuid.uuid4()}@example.test", role
    )
    machine, token = await provisioning_service.create_machine(
        db_session, user.id, f"iso-machine-{uuid.uuid4().hex[:8]}"
    )
    if studio is not None:
        db_session.add(
            StudioMembershipModel(
                studio_id=studio.id,
                user_id=user.id,
                role="owner",
                created_at=datetime.now(UTC),
            )
        )
        await db_session.flush()
    return user, machine, token


@pytest_asyncio.fixture
async def two_studios(
    db_session: AsyncSession,
) -> tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]]:
    """Studio A: an admin user acting in the second studio (header). Studio B:
    an internal-studio admin, with no membership in the second studio."""
    studio = await _second_studio(db_session)
    project = await _project(db_session, studio.id)
    _, _, token_a = await _member(db_session, studio)
    _, _, token_b = await _member(db_session)
    headers_a = {"Authorization": f"Bearer {token_a}", "X-Studio-Id": str(studio.id)}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    return studio, project, headers_a, headers_b


async def test_decisions_are_not_listed_read_or_transitioned_across_studios(
    client: AsyncClient,
    two_studios: tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]],
) -> None:
    _, project, headers_a, headers_b = two_studios
    created = await client.post(
        "/api/v1/decisions",
        headers=headers_a,
        json={
            "project_id": str(project.id),
            "title": "Studio A decision",
            "body": "Only studio A may read this.",
            "proposed_by_type": "user",
            "proposed_by_id": str(uuid.uuid4()),
        },
    )
    assert created.status_code == 201
    decision_id = created.json()["id"]

    listed_a = await client.get("/api/v1/decisions", headers=headers_a)
    assert listed_a.status_code == 200
    assert decision_id in {item["id"] for item in listed_a.json()}
    listed_b = await client.get("/api/v1/decisions", headers=headers_b)
    assert listed_b.status_code == 200
    assert decision_id not in {item["id"] for item in listed_b.json()}

    accepted_a = await client.post(f"/api/v1/decisions/{decision_id}/accept", headers=headers_a)
    assert accepted_a.status_code == 200
    assert accepted_a.json()["status"] == "accepted"

    # The second studio cannot reach it by id: same answer as an unknown id.
    unknown = await client.post(f"/api/v1/decisions/{uuid.uuid4()}/accept", headers=headers_b)
    foreign = await client.post(f"/api/v1/decisions/{decision_id}/accept", headers=headers_b)
    assert foreign.status_code == unknown.status_code == 404


async def test_idempotency_key_never_replays_another_studios_response(
    client: AsyncClient,
    two_studios: tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]],
) -> None:
    _, _, headers_a, headers_b = two_studios
    key = f"iso-{uuid.uuid4()}"
    payload = {"title": "Same key", "body": "Two studios.", "proposed_by_type": "user"}

    first = await client.post(
        "/api/v1/decisions",
        headers={**headers_a, "Idempotency-Key": key},
        json={**payload, "proposed_by_id": str(uuid.uuid4())},
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/decisions",
        headers={**headers_b, "Idempotency-Key": key},
        json={**payload, "proposed_by_id": str(uuid.uuid4())},
    )
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]


async def test_vault_notes_stay_inside_the_active_studio(
    client: AsyncClient,
    two_studios: tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]],
) -> None:
    _, _, headers_a, headers_b = two_studios
    slug = f"iso-note-{uuid.uuid4().hex[:10]}"
    created = await client.post(
        "/api/v1/vault/notes",
        headers=headers_a,
        json={
            "scope": "studio",
            "slug": slug,
            "note_type": "rule",
            "title": "Studio A note",
            "summary": "",
            "body": "Cross-studio notes are invisible.",
            "status": "draft",
            "tags": [],
            "anchors": [],
            "links": [],
        },
    )
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]

    tree_b = await client.get("/api/v1/vault/tree", headers=headers_b)
    assert tree_b.status_code == 200
    assert note_id not in {item["id"] for item in tree_b.json()["items"]}
    search_b = await client.get("/api/v1/vault/search", headers=headers_b, params={"q": slug})
    assert search_b.status_code == 200
    assert note_id not in {hit["note"]["id"] for hit in search_b.json()["items"]}

    fetched_b = await client.get(f"/api/v1/vault/notes/{note_id}", headers=headers_b)
    assert fetched_b.status_code == 404
    patched_b = await client.patch(
        f"/api/v1/vault/notes/{note_id}",
        headers=headers_b,
        json={"title": "hijacked", "expected_version": 1},
    )
    assert patched_b.status_code == 404

    patched_a = await client.patch(
        f"/api/v1/vault/notes/{note_id}",
        headers=headers_a,
        json={"title": "Studio A note v2", "expected_version": 1},
    )
    assert patched_a.status_code == 200
    assert patched_a.json()["title"] == "Studio A note v2"


async def test_library_resources_stay_inside_the_active_studio(
    client: AsyncClient,
    two_studios: tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]],
) -> None:
    _, _, headers_a, headers_b = two_studios
    created = await client.post("/api/v1/library", headers=headers_a, json=_rule_payload())
    assert created.status_code == 201, created.text
    resource_id = created.json()["id"]

    listed_b = await client.get("/api/v1/library", headers=headers_b)
    assert listed_b.status_code == 200
    assert resource_id not in {item["id"] for item in listed_b.json()}
    fetched_b = await client.get(f"/api/v1/library/{resource_id}", headers=headers_b)
    assert fetched_b.status_code == 404
    assert (
        await client.get(f"/api/v1/library/{resource_id}/versions", headers=headers_b)
    ).status_code == 404

    versioned_b = await client.post(
        f"/api/v1/library/{resource_id}/versions",
        headers=headers_b,
        json={
            "title": "hijacked",
            "content": {"content_schema": "studio.library.rule/v1", "text": "x"},
        },
    )
    assert versioned_b.status_code == 404

    versioned_a = await client.post(
        f"/api/v1/library/{resource_id}/versions",
        headers=headers_a,
        json={
            "title": "Studio A v2",
            "content": {"content_schema": "studio.library.rule/v1", "text": "x"},
        },
    )
    assert versioned_a.status_code == 201
    assert versioned_a.json()["version"] == 2


async def test_runtimes_stay_inside_the_active_studio(
    client: AsyncClient,
    two_studios: tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]],
) -> None:
    _, _, headers_a, headers_b = two_studios
    created = await client.post(
        "/api/v1/runtimes",
        headers=headers_a,
        json={"provider_ref": "local", "model_ref": "iso-model"},
    )
    assert created.status_code == 201, created.text
    runtime_id = created.json()["id"]

    listed_b = await client.get("/api/v1/runtimes", headers=headers_b)
    assert listed_b.status_code == 200
    assert runtime_id not in {item["id"] for item in listed_b.json()}
    fetched_b = await client.get(f"/api/v1/runtimes/{runtime_id}", headers=headers_b)
    assert fetched_b.status_code == 404
    patched_b = await client.patch(
        f"/api/v1/runtimes/{runtime_id}",
        headers=headers_b,
        json={"update": {"model_ref": "hijacked"}, "expected_version": 1},
    )
    assert patched_b.status_code == 404

    patched_a = await client.patch(
        f"/api/v1/runtimes/{runtime_id}",
        headers=headers_a,
        json={"update": {"model_ref": "iso-model-v2"}, "expected_version": 1},
    )
    assert patched_a.status_code == 200
    assert patched_a.json()["model_ref"] == "iso-model-v2"


async def test_agents_are_not_listed_or_superseded_across_studios(
    client: AsyncClient,
    two_studios: tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]],
) -> None:
    _, _, headers_a, headers_b = two_studios
    legacy = await client.post(
        "/api/v1/agents", headers=headers_a, json={"display_name": "iso-legacy"}
    )
    assert legacy.status_code == 201, legacy.text
    legacy_id = legacy.json()["id"]
    canonical = await client.post(
        "/api/v1/agents/resolve-identity",
        headers=headers_a,
        json={
            "harness": "claude-code",
            "provider": "anthropic",
            "effective_model": f"iso-model-{uuid.uuid4().hex[:8]}",
        },
    )
    assert canonical.status_code == 201, canonical.text
    canonical_id = canonical.json()["agent"]["id"]

    listed_b = await client.get("/api/v1/agents", headers=headers_b)
    assert listed_b.status_code == 200
    assert legacy_id not in {item["id"] for item in listed_b.json()}

    superseded_b = await client.post(
        f"/api/v1/agents/{legacy_id}/supersede",
        headers=headers_b,
        json={"canonical_agent_id": canonical_id},
    )
    assert superseded_b.status_code == 404

    superseded_a = await client.post(
        f"/api/v1/agents/{legacy_id}/supersede",
        headers=headers_a,
        json={"canonical_agent_id": canonical_id},
    )
    assert superseded_a.status_code == 200
    assert superseded_a.json()["superseded_by_agent_id"] == canonical_id


async def test_budget_policies_stay_inside_the_active_studio(
    client: AsyncClient,
    two_studios: tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]],
) -> None:
    _, project, headers_a, headers_b = two_studios
    payload = {
        "mode": "alert_only",
        "period": "month",
        "currency": "EUR",
        "unknown_cost": "ignore",
        "late_usage": "release",
        "settle_after_seconds": 60,
        "alert_thresholds": [50, 100],
    }
    created = await client.put(
        f"/api/v1/projects/{project.id}/budget-policy", headers=headers_a, json=payload
    )
    assert created.status_code == 200, created.text

    unknown_project = await client.get(f"/api/v1/projects/{uuid.uuid4()}/budget", headers=headers_b)
    foreign_project = await client.get(f"/api/v1/projects/{project.id}/budget", headers=headers_b)
    assert foreign_project.status_code == unknown_project.status_code

    denied = await client.put(
        f"/api/v1/projects/{project.id}/budget-policy", headers=headers_b, json=payload
    )
    assert denied.status_code == unknown_project.status_code

    own = await client.get(f"/api/v1/projects/{project.id}/budget", headers=headers_a)
    assert own.status_code == 200
    assert own.json()["project_id"] == str(project.id)


async def test_transfers_and_their_quota_stay_inside_the_active_studio(
    client: AsyncClient,
    two_studios: tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]],
) -> None:
    _, project, headers_a, headers_b = two_studios
    created = await client.post(
        "/api/v1/transfers",
        headers=headers_a,
        json={
            "category": "temporary",
            "filename": "iso.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 1024,
            "project_id": str(project.id),
        },
    )
    assert created.status_code == 201, created.text
    transfer_id = created.json()["id"]

    listed_b = await client.get("/api/v1/transfers", headers=headers_b)
    assert listed_b.status_code == 200
    assert transfer_id not in {item["id"] for item in listed_b.json()}
    fetched_b = await client.get(f"/api/v1/transfers/{transfer_id}", headers=headers_b)
    assert fetched_b.status_code == 404
    assert (
        await client.post(f"/api/v1/transfers/{transfer_id}/download-url", headers=headers_b)
    ).status_code == 404

    acknowledged_b = await client.post(
        f"/api/v1/transfers/{transfer_id}/downloaded", headers=headers_b
    )
    assert acknowledged_b.status_code == 404

    acknowledged_a = await client.post(
        f"/api/v1/transfers/{transfer_id}/downloaded", headers=headers_a
    )
    assert acknowledged_a.status_code == 200
    assert acknowledged_a.json()["downloaded_at"] is not None

    unscoped = await client.post(
        "/api/v1/transfers",
        headers=headers_a,
        json={
            "category": "temporary",
            "filename": "iso-unscoped.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 2048,
        },
    )
    assert unscoped.status_code == 201, unscoped.text
    consumption_a = await client.get("/api/v1/transfers/consumption", headers=headers_a)
    consumption_b = await client.get("/api/v1/transfers/consumption", headers=headers_b)
    assert consumption_a.status_code == consumption_b.status_code == 200
    assert consumption_a.json()["consumed_bytes"] == 2048
    assert consumption_b.json()["consumed_bytes"] == 0


async def test_upload_urls_are_never_signed_for_another_studios_transfer(
    client: AsyncClient,
    two_studios: tuple[StudioModel, ProjectModel, dict[str, str], dict[str, str]],
) -> None:
    _, project, headers_a, headers_b = two_studios
    created = await client.post(
        "/api/v1/transfers",
        headers=headers_a,
        json={
            "category": "temporary",
            "filename": "iso-upload.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 1024,
            "project_id": str(project.id),
        },
    )
    assert created.status_code == 201, created.text
    base = f"/api/v1/transfers/{created.json()['id']}"
    calls = [
        ("post", f"{base}/upload/initiate", {"content_md5": "1B2M2Y8AsgTpgAmY7PhCfg=="}),
        ("post", f"{base}/upload/refresh-parts", {"upload_id": "x", "part_numbers": [1]}),
        ("post", f"{base}/upload/complete", {"size_bytes": 1024, "sha256": "0" * 64}),
        ("delete", base, None),
    ]
    for method, url, payload in calls:
        denied = await client.request(method, url, headers=headers_b, json=payload)
        assert denied.status_code == 404, (url, denied.status_code, denied.text)

    assert (await client.get(base, headers=headers_a)).status_code == 200
