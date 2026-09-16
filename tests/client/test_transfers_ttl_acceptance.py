"""Real end-to-end acceptance test for DEC-0037 (roadmap step 7, P2 "Reprise
multipart apres expiration des URLs"): a multipart upload interrupted long
enough to genuinely outlive its presigned part URLs' TTL, resumed after a
simulated client restart (same SQLite outbox file, brand-new client objects —
not just the same process retrying), refreshing and uploading only the parts
storage doesn't already have, against real MinIO. No mocks anywhere in this
file: real FastAPI app (in-process ASGI transport, no network hop needed for
the API itself), real Postgres transaction, real MinIO for every byte."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from studio_api.db.models.project import ProjectModel
from studio_api.storage.provider import get_storage
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.outbox import OutboxStore, connect, transaction
from studio_client.tokens import MemoryTokenStore
from studio_client.transfers import TransferClient
from studio_contracts.transfers import TransferCategory, TransferCreate, TransferStatus

_PART_SIZE_BYTES = 64 * 1024 * 1024  # must match services/api PART_SIZE_BYTES


@pytest.fixture(autouse=True)
def _short_presigned_ttl(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`get_storage()` is process-wide `lru_cache`d (DEC-0026) — clearing it
    around this test is what makes a freshly-set short TTL actually apply to
    the presigned URLs the running app hands out, instead of whatever TTL
    happened to be cached from an earlier test/request."""
    monkeypatch.setenv("STUDIO_PRESIGNED_URL_TTL_SECONDS", "2")
    get_storage.cache_clear()
    yield
    get_storage.cache_clear()


async def test_multipart_upload_resumes_after_real_ttl_expiration_and_client_restart(
    tmp_path: Path,
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
) -> None:
    file_path = tmp_path / "big.bin"
    part1 = b"A" * _PART_SIZE_BYTES
    part2 = b"B" * _PART_SIZE_BYTES
    tail = b"C" * 4096
    payload = part1 + part2 + tail
    file_path.write_bytes(payload)
    outbox_path = tmp_path / "outbox.sqlite3"

    async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
        transfer = await api.create_transfer(
            TransferCreate(
                project_id=project.id,
                category=TransferCategory.TEMPORARY,
                filename="big.bin",
                content_type="application/octet-stream",
                size_bytes=len(payload),
            ),
            idempotency_key=str(uuid.uuid4()),
        )

        initiate = await api.initiate_upload(transfer.id)
        assert initiate.multipart is True
        assert initiate.upload_id is not None
        assert initiate.part_urls is not None
        assert initiate.part_size_bytes == _PART_SIZE_BYTES

        # "Process 1": upload only part 1 for real, straight to MinIO, then
        # record it locally exactly as `TransferClient` would — simulating
        # an interruption before parts 2/3 ever went out.
        async with httpx.AsyncClient(timeout=60.0) as raw:
            put_response = await raw.put(initiate.part_urls[1], content=part1)
        assert put_response.status_code == 200
        etag_1 = put_response.headers["ETag"].strip('"')

        store = OutboxStore(connect(outbox_path))
        with transaction(store.connection):
            store.save_multipart_upload(
                str(transfer.id),
                initiate.upload_id,
                str(file_path),
                initiate.part_size_bytes,
                initiate.part_urls,
                initiate.part_urls_expires_at,
            )
        with transaction(store.connection):
            store.record_completed_part(str(transfer.id), 1, etag_1)

    # Genuinely outlive the real TTL (2s) rather than racing it.
    await asyncio.sleep(3)

    # Confirm storage itself (not app logic) actually refuses the stale URL
    # for the part that was never sent, exactly the failure a real
    # long-interrupted upload would hit. Some S3-compatible backends return
    # a clean 4xx; others reset the connection outright for a large body
    # against an expired signature (observed in CI, not just locally) — both
    # are a genuine rejection, and `TransferClient` itself (exercised below)
    # already treats a transport-level failure on a first attempt the same
    # as a 403 (DEC-0037).
    stale_url_for_part_2 = initiate.part_urls[2]
    async with httpx.AsyncClient(timeout=60.0) as raw:
        try:
            rejected = await raw.put(stale_url_for_part_2, content=part2)
        except httpx.TransportError:
            pass
        else:
            assert rejected.status_code >= 400, (
                f"expected the real TTL to have expired, got {rejected.status_code}"
            )

    # "Process 2": brand-new StudioApiClient, OutboxStore and TransferClient
    # instances against the *same* SQLite file — a real restart, not the
    # same objects retrying. `upload()` must detect the existing state,
    # refresh only the missing parts (2 and 3), never re-upload part 1, and
    # produce a byte-identical object.
    resumed_store = OutboxStore(connect(outbox_path))
    state_before_resume = resumed_store.get_multipart_upload(str(transfer.id))
    assert state_before_resume is not None
    assert set(state_before_resume.completed_parts) == {1}

    async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
        client = TransferClient(api, resumed_store, http_client=httpx.AsyncClient(timeout=60.0))
        try:
            result = await client.upload(transfer, file_path)
        finally:
            await client.aclose()

    assert result.status == TransferStatus.READY
    assert resumed_store.get_multipart_upload(str(transfer.id)) is None

    async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
        download_client = TransferClient(api, resumed_store, http_client=httpx.AsyncClient())
        dest = tmp_path / "downloaded.bin"
        try:
            await download_client.download(result, dest)
        finally:
            await download_client.aclose()

    assert dest.read_bytes() == payload
