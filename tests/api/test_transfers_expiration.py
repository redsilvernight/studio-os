from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.transfer import TransferModel
from studio_api.services import transfers as transfers_service
from studio_api.settings import get_settings
from studio_api.storage.provider import StorageProvider


async def _upload_transfer(
    client: AsyncClient, auth_headers: dict[str, str], payload: bytes, category: str = "temporary"
) -> str:
    create = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "category": category,
            "filename": "report.bin",
            "content_type": "application/octet-stream",
            "size_bytes": len(payload),
        },
    )
    assert create.status_code == 201
    transfer_id = str(create.json()["id"])

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate", headers=auth_headers
    )
    upload_url = initiate.json()["upload_url"]
    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            upload_url, content=payload, headers={"Content-Type": "application/octet-stream"}
        )
    assert put_response.status_code == 200

    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert complete.status_code == 200
    return transfer_id


async def test_worker_deletes_expired_transfer_from_db_and_minio(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    transfer_id = await _upload_transfer(client, auth_headers, b"expired-payload")
    transfer = await db_session.get(TransferModel, uuid.UUID(transfer_id))
    assert transfer is not None
    transfer.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    storage = StorageProvider(get_settings())
    expired = await transfers_service.expire_transfers(db_session, storage)

    assert [t.id for t in expired] == [transfer.id]
    await db_session.refresh(transfer)
    assert transfer.status == "deleted"
    assert transfer.deleted_at is not None

    download = await client.post(
        f"/api/v1/transfers/{transfer_id}/download-url", headers=auth_headers
    )
    download_url = download.json()["download_url"]
    async with httpx.AsyncClient() as raw:
        get_response = await raw.get(download_url)
    assert get_response.status_code == 404


async def test_worker_never_touches_a_non_expired_transfer(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    future_id = await _upload_transfer(client, auth_headers, b"still-fresh")
    future_transfer = await db_session.get(TransferModel, uuid.UUID(future_id))
    assert future_transfer is not None
    future_transfer.expires_at = datetime.now(UTC) + timedelta(days=7)
    no_retention_id = await _upload_transfer(
        client, auth_headers, b"no-retention-set", category="asset"
    )
    await db_session.commit()

    storage = StorageProvider(get_settings())
    expired = await transfers_service.expire_transfers(db_session, storage)

    assert expired == []
    await db_session.refresh(future_transfer)
    assert future_transfer.status == "ready"
    no_retention_transfer = await db_session.get(TransferModel, uuid.UUID(no_retention_id))
    assert no_retention_transfer is not None
    assert no_retention_transfer.status == "ready"
    assert no_retention_transfer.expires_at is None


async def test_worker_rerun_is_idempotent(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    transfer_id = await _upload_transfer(client, auth_headers, b"expire-once")
    transfer = await db_session.get(TransferModel, uuid.UUID(transfer_id))
    assert transfer is not None
    transfer.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    storage = StorageProvider(get_settings())
    first_run = await transfers_service.expire_transfers(db_session, storage)
    assert len(first_run) == 1

    second_run = await transfers_service.expire_transfers(db_session, storage)
    assert second_run == []

    await db_session.refresh(transfer)
    assert transfer.status == "deleted"
