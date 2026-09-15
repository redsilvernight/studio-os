from __future__ import annotations

import base64
import hashlib
import uuid

import httpx
from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel
from studio_api.services import transfers as transfers_service
from studio_api.storage.provider import get_storage

MULTIPART_SIZE_BYTES = transfers_service.MULTIPART_THRESHOLD_BYTES + 1  # -> 3 parts
PART_SIZE_BYTES = transfers_service.PART_SIZE_BYTES


async def _create_multipart_transfer(
    client: AsyncClient, auth_headers: dict[str, str], *, size_bytes: int = MULTIPART_SIZE_BYTES
) -> tuple[str, str]:
    created = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "category": "temporary",
            "filename": "big.bin",
            "content_type": "application/octet-stream",
            "size_bytes": size_bytes,
        },
    )
    assert created.status_code == 201
    transfer_id = created.json()["id"]

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate", headers=auth_headers
    )
    assert initiate.status_code == 200
    body = initiate.json()
    assert body["multipart"] is True
    assert body["part_urls_expires_at"]
    return transfer_id, body["upload_id"]


async def test_refresh_parts_presigns_only_missing_and_reports_uploaded_from_storage(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """DEC-0037: `ListParts` (storage's own record) is the source of truth —
    a part already durably accepted is reported in `uploaded_parts` and
    never re-presigned, even though the API itself never persisted that
    fact anywhere."""
    transfer_id, upload_id = await _create_multipart_transfer(client, auth_headers)

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate", headers=auth_headers
    )
    body = initiate.json()
    upload_id = body["upload_id"]  # initiate always mints a fresh upload_id on replay
    part_urls = body["part_urls"]
    part1 = b"P" * PART_SIZE_BYTES
    async with httpx.AsyncClient(timeout=60.0) as raw:
        response = await raw.put(part_urls["1"], content=part1)
    assert response.status_code == 200

    refresh = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": upload_id},
    )
    assert refresh.status_code == 200
    body = refresh.json()
    assert body["upload_id"] == upload_id
    assert body["part_size_bytes"] == PART_SIZE_BYTES
    assert set(body["uploaded_parts"]) == {"1"}
    assert set(body["part_urls"]) == {"2", "3"}


async def test_refresh_parts_rejects_unknown_upload_id(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    transfer_id, _ = await _create_multipart_transfer(client, auth_headers)

    refresh = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": "not-a-real-upload-id"},
    )
    assert refresh.status_code == 409
    assert refresh.json()["detail"]["error_code"] == "unknown_upload_id"


async def test_refresh_parts_rejects_upload_id_from_a_different_transfer(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """`ListParts(Key=object_key, UploadId=upload_id)` is how the server
    verifies `upload_id` genuinely belongs to *this* transfer's object —
    borrowing another transfer's real `upload_id` must not pass."""
    transfer_a, _ = await _create_multipart_transfer(client, auth_headers)
    _, upload_id_b = await _create_multipart_transfer(client, auth_headers)

    refresh = await client.post(
        f"/api/v1/transfers/{transfer_a}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": upload_id_b},
    )
    assert refresh.status_code == 409
    assert refresh.json()["detail"]["error_code"] == "unknown_upload_id"


async def test_refresh_parts_rejects_part_size_mismatch(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    transfer_id, upload_id = await _create_multipart_transfer(client, auth_headers)

    refresh = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": upload_id, "part_size_bytes": PART_SIZE_BYTES + 1},
    )
    assert refresh.status_code == 409
    assert refresh.json()["detail"]["error_code"] == "part_size_mismatch"


async def test_refresh_parts_rejects_out_of_range_part_number(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    transfer_id, upload_id = await _create_multipart_transfer(client, auth_headers)

    refresh = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": upload_id, "part_numbers": [999]},
    )
    assert refresh.status_code == 422
    assert refresh.json()["detail"]["error_code"] == "invalid_part_number"


async def test_refresh_parts_rejects_already_ready_transfer(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = b"tiny"
    transfer = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "category": "temporary",
            "filename": "f.bin",
            "content_type": "application/octet-stream",
            "size_bytes": len(payload),
        },
    )
    transfer_id = transfer.json()["id"]
    content_md5 = base64.b64encode(hashlib.md5(payload).digest()).decode()
    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": content_md5},
    )
    async with httpx.AsyncClient() as raw:
        await raw.put(
            initiate.json()["upload_url"],
            content=payload,
            headers={"Content-Type": "application/octet-stream", "Content-MD5": content_md5},
        )
    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert complete.status_code == 200

    refresh = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": "irrelevant-because-already-ready"},
    )
    assert refresh.status_code == 409
    assert refresh.json()["detail"]["error_code"] == "transfer_already_ready"


async def test_refresh_parts_authorization_matrix(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    """Same rule as upload/initiate and upload/complete (TECH/04 Autorisation):
    sender or admin only — never the recipient, never a broadcast reader,
    never `readonly`."""
    recipient_user_id = other_machine[0].owner_user_id
    created = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "recipient_user_id": str(recipient_user_id),
            "category": "temporary",
            "filename": "big.bin",
            "content_type": "application/octet-stream",
            "size_bytes": MULTIPART_SIZE_BYTES,
        },
    )
    transfer_id = created.json()["id"]
    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate", headers=auth_headers
    )
    upload_id = initiate.json()["upload_id"]

    recipient_attempt = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=other_auth_headers,
        json={"upload_id": upload_id},
    )
    assert recipient_attempt.status_code == 403
    assert recipient_attempt.json()["detail"]["error_code"] == "forbidden"

    readonly_attempt = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=readonly_auth_headers,
        json={"upload_id": upload_id},
    )
    assert readonly_attempt.status_code == 403

    admin_attempt = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=admin_auth_headers,
        json={"upload_id": upload_id},
    )
    assert admin_attempt.status_code == 200

    sender_attempt = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": upload_id},
    )
    assert sender_attempt.status_code == 200


async def test_delete_transfer_aborts_dangling_multipart_upload(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """DEC-0037: a multipart upload nobody ever completed must not keep
    billing storage forever after its Transfer row is deleted."""
    transfer_id, upload_id = await _create_multipart_transfer(client, auth_headers)

    delete_response = await client.delete(f"/api/v1/transfers/{transfer_id}", headers=auth_headers)
    assert delete_response.status_code == 204

    refresh = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": upload_id},
    )
    assert refresh.status_code == 409
    assert refresh.json()["detail"]["error_code"] == "unknown_upload_id"


async def test_abort_stale_multipart_uploads_worker(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """`studio-admin transfers abort-stale-multipart` (DEC-0037): storage's
    own `Initiated` timestamp is the only signal available (the server never
    persists in-progress multipart state), so this drives age via a
    deliberately past-the-future cutoff (`older_than_days=-1`) rather than
    sleeping in the test."""
    transfer_id, upload_id = await _create_multipart_transfer(client, auth_headers)
    storage = get_storage()

    dry_run = await transfers_service.abort_stale_multipart_uploads(
        storage, older_than_days=-1, dry_run=True
    )
    assert any(u["upload_id"] == upload_id for u in dry_run)
    still_alive = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": upload_id},
    )
    assert still_alive.status_code == 200  # dry-run must not have touched it

    aborted = await transfers_service.abort_stale_multipart_uploads(
        storage, older_than_days=-1, dry_run=False
    )
    assert any(u["upload_id"] == upload_id for u in aborted)

    now_dead = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        headers=auth_headers,
        json={"upload_id": upload_id},
    )
    assert now_dead.status_code == 409
    assert now_dead.json()["detail"]["error_code"] == "unknown_upload_id"


async def test_refresh_parts_rejects_unauthenticated(client: AsyncClient) -> None:
    transfer_id = str(uuid.uuid4())
    response = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
        json={"upload_id": "whatever"},
    )
    assert response.status_code == 401
