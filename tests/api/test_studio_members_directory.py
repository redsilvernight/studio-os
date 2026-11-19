"""Per-studio directory `GET /api/v1/studio/members`: studio owner/admin only,
active studio's accounts only; `GET /users` stays operator-only."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.services import provisioning as provisioning_service


async def _studio_with_users(
    db_session: AsyncSession, roles: dict[str, str]
) -> tuple[StudioModel, dict[str, tuple[uuid.UUID, str]]]:
    studio = StudioModel(slug=f"studio-{uuid.uuid4().hex[:8]}", name="Studio")
    db_session.add(studio)
    await db_session.flush()
    out: dict[str, tuple[uuid.UUID, str]] = {}
    for label, studio_role in roles.items():
        user = await provisioning_service.create_user(
            db_session, f"{label} {studio.slug}", f"{label}-{studio.slug}@example.test", "developer"
        )
        db_session.add(
            StudioMembershipModel(studio_id=studio.id, user_id=user.id, role=studio_role)
        )
        _, token = await provisioning_service.create_machine(db_session, user.id, "m")
        out[label] = (user.id, token)
    await db_session.flush()
    return studio, out


def _h(token: str, studio: StudioModel) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Studio-Id": str(studio.id)}


async def test_studio_manager_lists_only_its_studio_members(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    studio, users = await _studio_with_users(db_session, {"boss": "admin", "dev": "member"})
    other, others = await _studio_with_users(db_session, {"stranger": "owner"})

    response = await client.get("/api/v1/studio/members", headers=_h(users["boss"][1], studio))
    assert response.status_code == 200, response.text
    ids = {u["id"] for u in response.json()}
    assert ids == {str(users["boss"][0]), str(users["dev"][0])}
    assert str(others["stranger"][0]) not in ids
    assert all("password_hash" not in u for u in response.json())

    filtered = await client.get(
        "/api/v1/studio/members",
        params={"q": "DEV ", "limit": 1},
        headers=_h(users["boss"][1], studio),
    )
    assert [u["id"] for u in filtered.json()] == [str(users["dev"][0])]

    mirror = await client.get("/api/v1/studio/members", headers=_h(others["stranger"][1], other))
    assert {u["id"] for u in mirror.json()} == {str(others["stranger"][0])}


async def test_plain_studio_member_is_forbidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    studio, users = await _studio_with_users(db_session, {"dev": "member", "eye": "viewer"})
    for label in ("dev", "eye"):
        response = await client.get("/api/v1/studio/members", headers=_h(users[label][1], studio))
        assert response.status_code == 403, response.text


async def test_users_directory_stays_operator_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    studio, users = await _studio_with_users(db_session, {"boss": "owner"})
    response = await client.get("/api/v1/users", headers=_h(users["boss"][1], studio))
    assert response.status_code == 403, response.text


async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/studio/members")).status_code == 401
