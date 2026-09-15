from __future__ import annotations

import asyncio
import uuid

import httpx
from studio_api.settings import get_settings
from studio_api.storage.provider import StorageProvider, safe_object_key


async def test_expired_upload_url_is_rejected_by_real_minio() -> None:
    """TECH/10_TEST_ACCEPTANCE.md scenario 'URL signee expiree'. The presigned
    TTL served by the running API is fixed at process start
    (`storage.provider.get_storage()` is `lru_cache`d over `Settings` read
    once), so this presigns directly with a short-lived `StorageProvider`
    built the same way (`.claude/rules/storage-transfers.md`) to get a URL
    that has genuinely expired by the time it's used, then confirms the real
    MinIO backend (not app logic) rejects it — the same guarantee a client
    that waited too long before uploading would hit in production."""
    settings = get_settings()
    short_lived = settings.model_copy(update={"presigned_url_ttl_seconds": 1})
    object_key = safe_object_key("expired-url-test", uuid.uuid4(), "payload.bin")
    upload_url = StorageProvider(short_lived).presign_put(
        object_key, content_type="application/octet-stream"
    )

    await asyncio.sleep(2)

    async with httpx.AsyncClient() as raw:
        response = await raw.put(
            upload_url,
            content=b"too late",
            headers={"Content-Type": "application/octet-stream"},
        )
    assert response.status_code >= 400, (
        f"expected the real storage backend to reject an expired presigned PUT, "
        f"got {response.status_code}: {response.text}"
    )


async def test_expired_download_url_is_rejected_by_real_minio() -> None:
    settings = get_settings()
    short_lived = settings.model_copy(update={"presigned_url_ttl_seconds": 1})
    object_key = safe_object_key("expired-url-test", uuid.uuid4(), "payload.bin")
    download_url = StorageProvider(short_lived).presign_get(object_key)

    await asyncio.sleep(2)

    async with httpx.AsyncClient() as raw:
        response = await raw.get(download_url)
    assert response.status_code >= 400, (
        f"expected the real storage backend to reject an expired presigned GET, "
        f"got {response.status_code}: {response.text}"
    )
