from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.transfer import TransferModel
from studio_api.services import provisioning as provisioning_service


async def _create_transfer(
    client: AsyncClient,
    auth_headers: dict[str, str],
    recipient_user_id: str | None = None,
) -> str:
    body: dict[str, object] = {
        "category": "temporary",
        "filename": "report.bin",
        "content_type": "application/octet-stream",
        "size_bytes": 13,
    }
    if recipient_user_id is not None:
        body["recipient_user_id"] = recipient_user_id
    response = await client.post("/api/v1/transfers", headers=auth_headers, json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_acknowledge_marks_downloaded_and_replay_preserves_timestamp(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    transfer_id = await _create_transfer(client, auth_headers)

    first = await client.post(f"/api/v1/transfers/{transfer_id}/downloaded", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "downloaded"
    assert first.json()["downloaded_at"] is not None

    replay = await client.post(
        f"/api/v1/transfers/{transfer_id}/downloaded", headers=auth_headers
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "downloaded"
    assert replay.json()["downloaded_at"] == first.json()["downloaded_at"]


async def test_recipient_may_acknowledge(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    me = await client.get("/api/v1/auth/me", headers=other_auth_headers)
    assert me.status_code == 200, me.text
    transfer_id = await _create_transfer(client, auth_headers, str(me.json()["user_id"]))

    ack = await client.post(
        f"/api/v1/transfers/{transfer_id}/downloaded", headers=other_auth_headers
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "downloaded"
    assert ack.json()["downloaded_at"] is not None


async def test_uninvolved_third_party_and_readonly_get_403(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    recipient = await provisioning_service.create_user(
        db_session, "Recipient", f"{uuid.uuid4()}@example.test", "developer"
    )
    transfer_id = await _create_transfer(client, auth_headers, str(recipient.id))
    for headers in (other_auth_headers, readonly_auth_headers):
        response = await client.post(
            f"/api/v1/transfers/{transfer_id}/downloaded", headers=headers
        )
        assert response.status_code == 403, response.text


async def test_readonly_recipient_cannot_acknowledge(
    client: AsyncClient, auth_headers: dict[str, str], readonly_auth_headers: dict[str, str]
) -> None:
    me = await client.get("/api/v1/auth/me", headers=readonly_auth_headers)
    assert me.status_code == 200, me.text
    transfer_id = await _create_transfer(client, auth_headers, str(me.json()["user_id"]))

    response = await client.post(
        f"/api/v1/transfers/{transfer_id}/downloaded", headers=readonly_auth_headers
    )
    assert response.status_code == 403, response.text


async def test_unknown_transfer_is_404(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        f"/api/v1/transfers/{uuid.uuid4()}/downloaded", headers=auth_headers
    )
    assert response.status_code == 404, response.text


async def test_acknowledge_deleted_transfer_is_409(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    transfer_id = await _create_transfer(client, auth_headers)
    transfer = await db_session.get(TransferModel, uuid.UUID(transfer_id))
    assert transfer is not None
    transfer.status = "deleted"
    await db_session.commit()

    response = await client.post(
        f"/api/v1/transfers/{transfer_id}/downloaded", headers=auth_headers
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error_code"] == "transfer_deleted"
