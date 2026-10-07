"""P05: write rights per scope (DEC-0187 D4) and the audit trail of a note."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.vault import VaultNoteModel
from studio_api.services import provisioning as provisioning_service

ADMIN_ONLY_STATUSES = ("validated", "superseded", "archived")


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create(
    client: AsyncClient, headers: dict[str, str], **payload: object
) -> dict[str, object]:
    body = {"scope": "studio", "slug": _slug("d4"), "title": "T", "body": "B", **payload}
    response = await client.post("/api/v1/vault/notes", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _headers_for(db_session: AsyncSession, role: str) -> dict[str, str]:
    user = await provisioning_service.create_user(
        db_session, role.title(), f"{uuid.uuid4()}@example.test", role
    )
    _, token = await provisioning_service.create_machine(db_session, user.id, f"{role}-m")
    return {"Authorization": f"Bearer {token}"}


async def _count_notes(db_session: AsyncSession, slug: str) -> int:
    return (
        await db_session.execute(
            select(func.count()).select_from(VaultNoteModel).where(VaultNoteModel.slug == slug)
        )
    ).scalar_one()


async def test_readonly_cannot_write_studio_scope(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
) -> None:
    slug = _slug("ro")
    created = await client.post(
        "/api/v1/vault/notes",
        headers=readonly_auth_headers,
        json={"scope": "studio", "slug": slug, "title": "T", "body": "B"},
    )
    assert created.status_code == 403
    assert await _count_notes(db_session, slug) == 0

    note = await _create(client, auth_headers)
    updated = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=readonly_auth_headers,
        json={"expected_version": 1, "title": "edited"},
    )
    assert updated.status_code == 403
    read = await client.get(f"/api/v1/vault/notes/{note['id']}", headers=readonly_auth_headers)
    assert read.status_code == 200
    assert read.json()["version"] == 1
    assert read.json()["title"] == "T"


@pytest.mark.parametrize("role", ["developer", "agent"])
@pytest.mark.parametrize("status", ["draft", "proposed"])
async def test_writers_create_and_edit_draft_or_proposed(
    client: AsyncClient, db_session: AsyncSession, role: str, status: str
) -> None:
    headers = await _headers_for(db_session, role)
    note = await _create(client, headers, status=status)
    edited = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=headers,
        json={"expected_version": 1, "body": "edited"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2


@pytest.mark.parametrize("role", ["developer", "agent"])
@pytest.mark.parametrize("status", ADMIN_ONLY_STATUSES)
async def test_admin_only_statuses_refused_to_non_admins(
    client: AsyncClient,
    db_session: AsyncSession,
    role: str,
    status: str,
) -> None:
    headers = await _headers_for(db_session, role)
    slug = _slug("adm")
    created = await client.post(
        "/api/v1/vault/notes",
        headers=headers,
        json={"scope": "studio", "slug": slug, "title": "T", "body": "B", "status": status},
    )
    # Refused either by the role check (403) or, for statuses a creation can
    # never carry, by the contract (422): in both cases nothing persists.
    assert created.status_code in (403, 422)
    assert await _count_notes(db_session, slug) == 0

    note = await _create(client, headers, status="proposed")
    promoted = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=headers,
        json={"expected_version": 1, "status": status},
    )
    assert promoted.status_code == 403


@pytest.mark.parametrize("status", ADMIN_ONLY_STATUSES)
async def test_admin_reaches_admin_only_statuses(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    status: str,
) -> None:
    note = await _create(client, auth_headers, status="proposed")
    promoted = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=admin_auth_headers,
        json={"expected_version": 1, "status": status},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["status"] == status


async def test_audit_trail_records_author_scope_version_and_time(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
) -> None:
    machine_model, _ = machine
    note = await _create(client, auth_headers, status="proposed")
    accepted = await client.patch(
        f"/api/v1/vault/notes/{note['id']}",
        headers=admin_auth_headers,
        json={"expected_version": 1, "status": "validated", "change_summary": "accepted"},
    )
    assert accepted.status_code == 200, accepted.text

    current = (await client.get(f"/api/v1/vault/notes/{note['id']}", headers=auth_headers)).json()
    assert current["scope"] == "studio"
    assert current["version"] == 2

    page = await client.get(f"/api/v1/vault/notes/{note['id']}/versions", headers=auth_headers)
    assert page.status_code == 200
    versions = sorted(page.json()["items"], key=lambda v: v["version"])
    assert [v["version"] for v in versions] == [1, 2]
    first, second = versions
    assert first["author_type"] == second["author_type"] == "user"
    assert first["author_id"] == str(machine_model.owner_user_id)
    assert second["author_id"] != first["author_id"]
    assert second["author_id"] == current["author_id"]
    assert second["change_summary"] == "accepted"
    first_at = datetime.fromisoformat(first["created_at"])
    second_at = datetime.fromisoformat(second["created_at"])
    assert first_at.tzinfo is not None
    assert second_at >= first_at
