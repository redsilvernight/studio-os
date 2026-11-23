"""`GET /api/v1/studio` — the active studio of the caller, with the motif an
operator entered when suspending it (0050). The console writes that motif; the
studio's own members must see it on the N5 suspended view.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.studio import INTERNAL_STUDIO_ID, StudioModel


async def test_the_active_studio_is_readable_by_any_member(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/studio", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(INTERNAL_STUDIO_ID)
    assert body["name"] == "Studio OS"
    assert body["status"] == "active"
    assert body["suspension_reason"] is None
    # Aggregate identity only: no project, file or note in the payload.
    assert set(body) == {
        "id",
        "slug",
        "name",
        "plan",
        "status",
        "suspension_reason",
        "is_internal",
        "version",
        "created_at",
        "updated_at",
    }


async def test_a_suspended_studio_exposes_its_reason(
    client: AsyncClient, db_session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    studio = await db_session.get(StudioModel, INTERNAL_STUDIO_ID)
    assert studio is not None
    studio.status = "suspended"
    studio.suspension_reason = "Paiement non régularisé depuis 21 jours"
    await db_session.flush()
    await db_session.refresh(studio)

    response = await client.get("/api/v1/studio", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "suspended"
    assert body["suspension_reason"] == "Paiement non régularisé depuis 21 jours"


async def test_the_studio_endpoint_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/studio")).status_code == 401


async def test_the_studio_endpoint_exposes_no_content(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = (await client.get("/api/v1/studio", headers=auth_headers)).json()
    for forbidden in ("projects", "files", "notes", "messages", "content"):
        assert forbidden not in body
