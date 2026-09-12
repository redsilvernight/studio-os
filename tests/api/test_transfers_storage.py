from __future__ import annotations

import hashlib
import uuid

import httpx
from httpx import AsyncClient


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
    transfer_id = await _create_transfer(client, auth_headers, len(payload))

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate", headers=auth_headers
    )
    assert initiate.status_code == 200
    body = initiate.json()
    assert body["multipart"] is False
    assert body["upload_url"]

    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            body["upload_url"],
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
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


async def test_upload_complete_rejects_size_mismatch(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = b"short payload"
    transfer_id = await _create_transfer(client, auth_headers, len(payload))

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
        json={"size_bytes": len(payload) + 1, "sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert complete.status_code == 422
    assert complete.json()["detail"]["error_code"] == "size_mismatch"


async def test_delete_transfer_removes_object_from_minio(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = b"delete-me"
    sha256 = hashlib.sha256(payload).hexdigest()
    transfer_id = await _create_transfer(client, auth_headers, len(payload))

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
    gathered out of order, without re-uploading finished parts."""
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
