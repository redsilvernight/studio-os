"""Break-glass exception access (DEC-0384, 0055).

Pins the contract: an operator request grants nothing until the studio owner
approves it; the window is capped at 24 hours and evaluated at read time;
another studio's owner and a plain member are refused; the journal is
append-only at the database level and never carries content.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.services import break_glass as break_glass_service
from studio_api.services import provisioning as provisioning_service

REQUEST_KEYS = {
    "id",
    "studio_id",
    "operator_ref",
    "reason",
    "scope",
    "requested_at",
    "status",
    "decided_by_user_id",
    "decided_at",
    "expires_at",
}
AUDIT_KEYS = {"id", "event", "request_id", "studio_id", "actor", "at"}


def _email() -> str:
    return f"{uuid.uuid4()}@example.test"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _user_machine(
    db_session: AsyncSession, *, role: str = "developer"
) -> tuple[UserModel, MachineModel, dict[str, str]]:
    user = await provisioning_service.create_user(
        db_session, f"Member {uuid.uuid4().hex[:6]}", _email(), role
    )
    machine, token = await provisioning_service.create_machine(
        db_session, user.id, f"machine-{uuid.uuid4().hex[:6]}"
    )
    return user, machine, _bearer(token)


async def _studio(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/studios", json={"name": f"Atelier {uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _request(
    client: AsyncClient, headers: dict[str, str], studio_id: str, *, reason: str = "Support case 42"
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/studios/{studio_id}/break-glass/requests",
        json={"reason": reason, "scope": "metadata"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_operator_request_grants_nothing_until_the_owner_approves(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    _, _, owner_headers = await _user_machine(db_session)
    studio_id = await _studio(client, owner_headers)

    created = await _request(client, admin_auth_headers, studio_id)
    assert set(created) == REQUEST_KEYS
    assert created["status"] == "requested"
    assert created["scope"] == "metadata"
    assert created["decided_by_user_id"] is None
    assert created["expires_at"] is None
    assert "content" not in " ".join(str(value) for value in created.values())

    approved = await client.post(
        f"/api/v1/studios/{studio_id}/break-glass/requests/{created['id']}/approve",
        json={"duration_hours": 4},
        headers=owner_headers,
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved"
    assert set(body) == REQUEST_KEYS
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert expires_at - datetime.fromisoformat(body["decided_at"]) == timedelta(hours=4)


async def test_duration_is_capped_at_24_hours(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    _, _, owner_headers = await _user_machine(db_session)
    studio_id = await _studio(client, owner_headers)
    created = await _request(client, admin_auth_headers, studio_id)
    url = f"/api/v1/studios/{studio_id}/break-glass/requests/{created['id']}/approve"

    too_long = await client.post(url, json={"duration_hours": 25}, headers=owner_headers)
    assert too_long.status_code == 422
    zero = await client.post(url, json={"duration_hours": 0}, headers=owner_headers)
    assert zero.status_code == 422

    still_pending = await client.get(
        f"/api/v1/studios/{studio_id}/break-glass/requests", headers=owner_headers
    )
    assert still_pending.json()[0]["status"] == "requested"


async def test_expiry_is_evaluated_at_read_time(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    _, _, owner_headers = await _user_machine(db_session)
    studio_id = await _studio(client, owner_headers)
    created = await _request(client, admin_auth_headers, studio_id)
    approved = await client.post(
        f"/api/v1/studios/{studio_id}/break-glass/requests/{created['id']}/approve",
        json={"duration_hours": 1},
        headers=owner_headers,
    )
    assert approved.status_code == 200, approved.text

    later = datetime.now(UTC) + timedelta(hours=2)
    expired = await break_glass_service.expire_due(db_session, uuid.UUID(studio_id), now=later)
    await db_session.commit()
    assert [row.status for row in expired] == ["expired"]

    listed = await client.get(
        f"/api/v1/studios/{studio_id}/break-glass/requests", headers=owner_headers
    )
    assert listed.json()[0]["status"] == "expired"
    audit = await client.get(
        f"/api/v1/studios/{studio_id}/break-glass/audit", headers=owner_headers
    )
    assert [row["event"] for row in audit.json()] == [
        "requested",
        "approved",
        "expired",
    ]


async def test_non_owner_cannot_decide_or_read_the_queue(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    _, _, owner_headers = await _user_machine(db_session)
    studio_id = await _studio(client, owner_headers)
    created = await _request(client, admin_auth_headers, studio_id)

    _, _, member_headers = await _user_machine(db_session)
    assert (
        await client.get(
            f"/api/v1/studios/{studio_id}/break-glass/requests", headers=member_headers
        )
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/studios/{studio_id}/break-glass/audit", headers=member_headers)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/studios/{studio_id}/break-glass/requests/{created['id']}/approve",
            json={"duration_hours": 1},
            headers=member_headers,
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/studios/{studio_id}/break-glass/requests/{created['id']}/deny",
            headers=member_headers,
        )
    ).status_code == 403


async def test_only_the_owner_revokes_an_open_window(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    _, _, owner_headers = await _user_machine(db_session)
    studio_id = await _studio(client, owner_headers)
    created = await _request(client, admin_auth_headers, studio_id)
    url = f"/api/v1/studios/{studio_id}/break-glass/requests/{created['id']}"

    assert (await client.post(f"{url}/revoke", headers=owner_headers)).status_code == 409
    assert (
        await client.post(f"{url}/approve", json={"duration_hours": 2}, headers=owner_headers)
    ).status_code == 200
    revoked = await client.post(f"{url}/revoke", headers=owner_headers)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    assert (await client.post(f"{url}/revoke", headers=owner_headers)).status_code == 409


async def test_denial_and_studio_isolation(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    _, _, owner_headers = await _user_machine(db_session)
    other_owner_headers = (await _user_machine(db_session))[2]
    studio_id = await _studio(client, owner_headers)
    other_studio_id = await _studio(client, other_owner_headers)
    created = await _request(client, admin_auth_headers, studio_id)
    url = f"/api/v1/studios/{studio_id}/break-glass/requests/{created['id']}"

    denied = await client.post(f"{url}/deny", headers=owner_headers)
    assert denied.status_code == 200, denied.text
    assert denied.json()["status"] == "denied"

    # The other studio's owner sees neither the request nor the journal.
    assert (await client.post(f"{url}/revoke", headers=other_owner_headers)).status_code == 403
    foreign_requests = await client.get(
        f"/api/v1/studios/{other_studio_id}/break-glass/requests", headers=other_owner_headers
    )
    assert foreign_requests.json() == []
    assert (
        await client.get(
            f"/api/v1/studios/{other_studio_id}/break-glass/audit", headers=other_owner_headers
        )
    ).json() == []
    # A request id sent under another studio's path is a plain 404.
    wrong_path = await client.post(
        f"/api/v1/studios/{other_studio_id}/break-glass/requests/{created['id']}/deny",
        headers=other_owner_headers,
    )
    assert wrong_path.status_code == 404


async def test_operator_without_the_flag_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, headers = await _user_machine(db_session)
    studio_id = await _studio(client, headers)

    response = await client.post(
        f"/api/v1/studios/{studio_id}/break-glass/requests",
        json={"reason": "Support case 13", "scope": "metadata"},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["resource"] == "instance"


async def test_audit_is_append_only(engine: AsyncEngine, db_session: AsyncSession) -> None:
    studio_id = uuid.uuid4()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(
            text(
                "INSERT INTO break_glass_audit (id, event, request_id, studio_id, actor) "
                "VALUES (:id, 'requested', :request_id, :studio_id, 'operator:test@example.test')"
            ),
            {"id": uuid.uuid4(), "request_id": uuid.uuid4(), "studio_id": studio_id},
        )
        with pytest.raises(DBAPIError):
            await connection.execute(text("UPDATE break_glass_audit SET actor = 'rewritten'"))
        await transaction.rollback()

    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(
            text(
                "INSERT INTO break_glass_audit (id, event, request_id, studio_id, actor) "
                "VALUES (:id, 'requested', :request_id, :studio_id, 'operator:test@example.test')"
            ),
            {"id": uuid.uuid4(), "request_id": uuid.uuid4(), "studio_id": studio_id},
        )
        with pytest.raises(DBAPIError):
            await connection.execute(text("DELETE FROM break_glass_audit"))
        await transaction.rollback()


async def test_journal_holds_no_content_and_every_transition_is_written(
    client: AsyncClient, db_session: AsyncSession, admin_auth_headers: dict[str, str]
) -> None:
    _, _, owner_headers = await _user_machine(db_session)
    studio_id = await _studio(client, owner_headers)
    created = await _request(client, admin_auth_headers, studio_id)
    url = f"/api/v1/studios/{studio_id}/break-glass/requests/{created['id']}"
    assert (
        await client.post(f"{url}/approve", json={"duration_hours": 1}, headers=owner_headers)
    ).status_code == 200
    assert (await client.post(f"{url}/revoke", headers=owner_headers)).status_code == 200

    audit = (
        await client.get(f"/api/v1/studios/{studio_id}/break-glass/audit", headers=owner_headers)
    ).json()
    assert [row["event"] for row in audit] == ["requested", "approved", "revoked"]
    assert all(set(row) == AUDIT_KEYS for row in audit)
    assert all(row["studio_id"] == studio_id for row in audit)
    assert all(row["actor"].startswith(("operator:", "user:")) for row in audit)
