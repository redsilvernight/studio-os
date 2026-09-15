from __future__ import annotations

import base64
import hashlib
import uuid

import httpx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.transfer import TransferModel


def _md5_b64(payload: bytes) -> str:
    return base64.b64encode(hashlib.md5(payload).digest()).decode()


async def _create_transfer(
    client: AsyncClient, auth_headers: dict[str, str], size_bytes: int
) -> str:
    response = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "category": "temporary",
            "filename": "report.bin",
            "content_type": "application/octet-stream",
            "size_bytes": size_bytes,
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


async def test_small_file_uploads_and_downloads_through_real_minio(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Golden rule (.claude/rules/storage-transfers.md): FastAPI only ever hands
    out a pre-signed URL, the client talks to MinIO directly for both upload
    and download."""
    payload = b"studio-os integration payload" * 1000
    sha256 = hashlib.sha256(payload).hexdigest()
    content_md5 = _md5_b64(payload)
    transfer_id = await _create_transfer(client, auth_headers, len(payload))

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": content_md5},
    )
    assert initiate.status_code == 200
    body = initiate.json()
    assert body["multipart"] is False
    assert body["upload_url"]

    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            body["upload_url"],
            content=payload,
            headers={"Content-Type": "application/octet-stream", "Content-MD5": content_md5},
        )
    assert put_response.status_code == 200

    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload), "sha256": sha256},
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "ready"

    download = await client.post(
        f"/api/v1/transfers/{transfer_id}/download-url", headers=auth_headers
    )
    assert download.status_code == 200
    download_url = download.json()["download_url"]

    async with httpx.AsyncClient() as raw:
        get_response = await raw.get(download_url)
    assert get_response.status_code == 200
    assert get_response.content == payload


async def test_upload_initiate_rejects_missing_content_md5(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Golden-rule corollary (DEC-0025): the single-PUT path can only be
    verified server-side if the client commits to a Content-MD5 up front."""
    transfer_id = await _create_transfer(client, auth_headers, size_bytes=13)

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate", headers=auth_headers
    )
    assert initiate.status_code == 422
    assert initiate.json()["detail"]["error_code"] == "missing_content_md5"


async def test_upload_rejected_by_minio_on_content_md5_mismatch(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """DEC-0025: presigning the PUT with Content-MD5 makes MinIO itself refuse
    a byte mismatch at upload time (`BadDigest`) — no bytes ever reach the API
    process, and the transfer can never be silently marked `ready` off
    corrupted/tampered bytes."""
    payload = b"the real bytes actually being uploaded"
    declared_md5 = _md5_b64(b"different bytes than what gets uploaded")
    transfer_id = await _create_transfer(client, auth_headers, len(payload))

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": declared_md5},
    )
    assert initiate.status_code == 200
    upload_url = initiate.json()["upload_url"]

    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            upload_url,
            content=payload,
            headers={"Content-Type": "application/octet-stream", "Content-MD5": declared_md5},
        )
    assert put_response.status_code == 400
    assert "BadDigest" in put_response.text

    # Nothing was ever stored, so completion (if attempted anyway) can't find
    # a matching object to mark ready.
    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert complete.status_code == 422
    assert complete.json()["detail"]["error_code"] == "object_not_found"


async def test_upload_complete_rejects_content_md5_mismatch_defense_in_depth(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Even if the stored `content_md5` metadata and the real object ever
    disagree (e.g. a bug, or a future storage backend that enforces
    Content-MD5 less strictly than this MinIO build), `complete_upload`'s own
    re-check (services/transfers.py) must still refuse to mark `ready`."""
    payload = b"legitimately uploaded bytes"
    content_md5 = _md5_b64(payload)
    transfer_id = await _create_transfer(client, auth_headers, len(payload))

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": content_md5},
    )
    upload_url = initiate.json()["upload_url"]
    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            upload_url,
            content=payload,
            headers={"Content-Type": "application/octet-stream", "Content-MD5": content_md5},
        )
    assert put_response.status_code == 200

    # Simulate the metadata and storage channels disagreeing about what was
    # actually uploaded.
    transfer = await db_session.get(TransferModel, uuid.UUID(transfer_id))
    assert transfer is not None
    transfer.content_md5 = _md5_b64(b"not what was actually uploaded")
    await db_session.commit()

    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert complete.status_code == 422
    assert complete.json()["detail"]["error_code"] == "content_md5_mismatch"


async def test_upload_complete_rejects_size_mismatch(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = b"short payload"
    content_md5 = _md5_b64(payload)
    transfer_id = await _create_transfer(client, auth_headers, len(payload))

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": content_md5},
    )
    upload_url = initiate.json()["upload_url"]

    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            upload_url,
            content=payload,
            headers={"Content-Type": "application/octet-stream", "Content-MD5": content_md5},
        )
    assert put_response.status_code == 200

    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload) + 1, "sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert complete.status_code == 422
    assert complete.json()["detail"]["error_code"] == "size_mismatch"


async def test_upload_complete_rejects_size_inflated_past_quota_reservation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """DEC-0025 regression: quota (DEC-0019) is enforced against the size
    declared at creation. Before this fix, `complete_upload` trusted the
    completion request's `size_bytes` at face value and overwrote
    `Transfer.size_bytes` with it — a client could declare a tiny size to pass
    the quota check, then complete with a much larger real size, silently
    exceeding the granted quota. The real object here really is 14 bytes
    (matching the actual upload), but the client claims a different size at
    completion than it reserved at creation — that mismatch alone must be
    rejected before storage is even consulted."""
    payload = b"14-byte-value!"
    assert len(payload) == 14
    content_md5 = _md5_b64(payload)
    transfer_id = await _create_transfer(client, auth_headers, size_bytes=1)

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": content_md5},
    )
    assert initiate.status_code == 200
    upload_url = initiate.json()["upload_url"]
    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            upload_url,
            content=payload,
            headers={"Content-Type": "application/octet-stream", "Content-MD5": content_md5},
        )
    assert put_response.status_code == 200

    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert complete.status_code == 422
    detail = complete.json()["detail"]
    assert detail["error_code"] == "size_mismatch"
    assert detail["expected"] == 1
    assert detail["actual"] == len(payload)


async def test_upload_initiate_rejects_already_ready_transfer(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A completed transfer's `content_md5`/object must not be silently
    replaceable by calling initiate again (DEC-0025)."""
    payload = b"already-uploaded"
    content_md5 = _md5_b64(payload)
    transfer_id = await _create_transfer(client, auth_headers, len(payload))

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": content_md5},
    )
    upload_url = initiate.json()["upload_url"]
    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            upload_url,
            content=payload,
            headers={"Content-Type": "application/octet-stream", "Content-MD5": content_md5},
        )
    assert put_response.status_code == 200
    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert complete.status_code == 200

    reinitiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": content_md5},
    )
    assert reinitiate.status_code == 409
    assert reinitiate.json()["detail"]["error_code"] == "transfer_already_ready"


async def test_delete_transfer_removes_object_from_minio(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = b"delete-me"
    sha256 = hashlib.sha256(payload).hexdigest()
    content_md5 = _md5_b64(payload)
    transfer_id = await _create_transfer(client, auth_headers, len(payload))

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": content_md5},
    )
    upload_url = initiate.json()["upload_url"]
    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            upload_url,
            content=payload,
            headers={"Content-Type": "application/octet-stream", "Content-MD5": content_md5},
        )
    assert put_response.status_code == 200
    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload), "sha256": sha256},
    )
    assert complete.status_code == 200

    delete_response = await client.delete(f"/api/v1/transfers/{transfer_id}", headers=auth_headers)
    assert delete_response.status_code == 204

    # Object is gone from MinIO: a fresh download URL now points at nothing.
    download = await client.post(
        f"/api/v1/transfers/{transfer_id}/download-url", headers=auth_headers
    )
    download_url = download.json()["download_url"]
    async with httpx.AsyncClient() as raw:
        get_response = await raw.get(download_url)
    assert get_response.status_code == 404


async def test_multipart_upload_resumes_across_independently_uploaded_parts(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Large-file path (TECH/06_STORAGE_TRANSFER_SPEC.md): parts are uploaded
    independently straight to storage and can be completed after being
    gathered out of order, without re-uploading finished parts. No
    `content_md5` involved — the multipart path has no whole-object checksum
    (DEC-0025)."""
    part_size = 64 * 1024 * 1024
    part_1 = uuid.uuid4().bytes * (part_size // 16)
    part_2 = uuid.uuid4().bytes * (part_size // 16)
    part_3 = b"tail-part-bytes"
    payload = part_1 + part_2 + part_3
    sha256 = hashlib.sha256(payload).hexdigest()

    transfer_id = await _create_transfer(client, auth_headers, len(payload))

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate", headers=auth_headers
    )
    assert initiate.status_code == 200
    body = initiate.json()
    assert body["multipart"] is True
    upload_id = body["upload_id"]
    part_urls = body["part_urls"]
    assert set(part_urls) == {"1", "2", "3"}

    parts = [part_1, part_2, part_3]
    etags: dict[int, str] = {}
    async with httpx.AsyncClient(timeout=60.0) as raw:
        # Upload part 3 then part 1 first, simulating a resume that gathers
        # whichever parts finished before an interruption, in any order.
        for number in (3, 1, 2):
            response = await raw.put(part_urls[str(number)], content=parts[number - 1])
            assert response.status_code == 200
            etags[number] = response.headers["ETag"]

    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={
            "size_bytes": len(payload),
            "sha256": sha256,
            "upload_id": upload_id,
            "parts": etags,
        },
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "ready"

    download = await client.post(
        f"/api/v1/transfers/{transfer_id}/download-url", headers=auth_headers
    )
    download_url = download.json()["download_url"]
    async with httpx.AsyncClient(timeout=60.0) as raw:
        get_response = await raw.get(download_url)
    assert get_response.status_code == 200
    assert get_response.content == payload
