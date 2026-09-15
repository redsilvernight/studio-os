"""Real end-to-end acceptance test for the last open "Tests transfer" scenario
of `docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/10_TEST_ACCEPTANCE.md`
("fichier 1 Go multipart") and the matching item in
`docs/ROADMAP_CORRECTIONS_AUDIT.md` step 7 ("fichier multipart de 1 Go reel").

Real Postgres (in-process ASGI transport for the API itself, per
`tests/client/conftest.py`) and real MinIO for every byte — no mocks. The
source/downloaded files and every part PUT stay bounded to a `_CHUNK_BYTES`
(1 MiB) or `_PART_SIZE_BYTES` (64 MiB) buffer at a time; nothing here ever
holds the full 1 GiB payload in memory at once (per the audit brief:
"eviter d'allouer plusieurs gigaoctets en memoire"). The MinIO object is
removed in a `finally` block regardless of outcome."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import httpx
from httpx import ASGITransport
from studio_api.db.models.project import ProjectModel
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.outbox import OutboxStore, connect, transaction
from studio_client.tokens import MemoryTokenStore
from studio_client.transfers import TransferClient
from studio_contracts.transfers import TransferCategory, TransferCreate, TransferStatus

_PART_SIZE_BYTES = 64 * 1024 * 1024  # must match services/api PART_SIZE_BYTES
_PART_COUNT = 16  # 16 * 64 MiB = 1 GiB exactly
_TOTAL_BYTES = _PART_SIZE_BYTES * _PART_COUNT
_INTERRUPT_AFTER_PART = 8  # upload the first half for real, then "restart"
_CHUNK_BYTES = 1024 * 1024


def _write_random_file(path: Path, total_bytes: int) -> None:
    """Streams the payload straight to disk in 1 MiB chunks — never builds a
    single `bytes` object anywhere near `total_bytes` long."""
    with path.open("wb") as handle:
        written = 0
        while written < total_bytes:
            n = min(_CHUNK_BYTES, total_bytes - written)
            handle.write(os.urandom(n))
            written += n


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_part(path: Path, part_number: int) -> bytes:
    offset = (part_number - 1) * _PART_SIZE_BYTES
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read(_PART_SIZE_BYTES)


async def test_multipart_upload_1gb_streamed_real_interruption_and_resume(
    tmp_path: Path,
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
) -> None:
    source_path = tmp_path / "source-1gb.bin"
    dest_path = tmp_path / "downloaded-1gb.bin"
    outbox_path = tmp_path / "outbox.sqlite3"

    _write_random_file(source_path, _TOTAL_BYTES)
    assert source_path.stat().st_size == _TOTAL_BYTES
    source_sha256 = _sha256_of(source_path)

    transfer_id: uuid.UUID | None = None
    open_stores: list[OutboxStore] = []
    try:
        async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
            transfer = await api.create_transfer(
                TransferCreate(
                    project_id=project.id,
                    category=TransferCategory.TEMPORARY,
                    filename="source-1gb.bin",
                    content_type="application/octet-stream",
                    size_bytes=_TOTAL_BYTES,
                ),
                idempotency_key=str(uuid.uuid4()),
            )
            transfer_id = transfer.id

            initiate = await api.initiate_upload(transfer.id)
            assert initiate.multipart is True
            assert initiate.upload_id is not None
            assert initiate.part_urls is not None
            assert initiate.part_size_bytes == _PART_SIZE_BYTES
            assert set(initiate.part_urls) == set(range(1, _PART_COUNT + 1))

            # "Process 1": upload the first half for real, straight to MinIO,
            # recording each completed part locally exactly as `TransferClient`
            # would — simulating an interruption halfway through.
            store = OutboxStore(connect(outbox_path))
            open_stores.append(store)
            with transaction(store.connection):
                store.save_multipart_upload(
                    str(transfer.id),
                    initiate.upload_id,
                    str(source_path),
                    initiate.part_size_bytes,
                    initiate.part_urls,
                    initiate.part_urls_expires_at,
                )
            async with httpx.AsyncClient(timeout=120.0) as raw:
                for part_number in range(1, _INTERRUPT_AFTER_PART + 1):
                    chunk = _read_part(source_path, part_number)
                    response = await raw.put(initiate.part_urls[part_number], content=chunk)
                    assert response.status_code == 200
                    etag = response.headers["ETag"].strip('"')
                    with transaction(store.connection):
                        store.record_completed_part(str(transfer.id), part_number, etag)

        precheck_store = OutboxStore(connect(outbox_path))
        open_stores.append(precheck_store)
        state_before_resume_check = precheck_store.get_multipart_upload(str(transfer_id))
        assert state_before_resume_check is not None
        assert set(state_before_resume_check.completed_parts) == set(
            range(1, _INTERRUPT_AFTER_PART + 1)
        )

        # "Process 2": brand-new StudioApiClient, OutboxStore and
        # TransferClient instances against the *same* SQLite file — a real
        # restart. `upload()` must resume from parts 9-16 only, never
        # re-uploading 1-8, and produce a byte-identical object.
        resumed_store = OutboxStore(connect(outbox_path))
        open_stores.append(resumed_store)
        async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
            upload_client = TransferClient(
                api, resumed_store, http_client=httpx.AsyncClient(timeout=120.0)
            )
            try:
                result = await upload_client.upload(transfer, source_path)
            finally:
                await upload_client.aclose()

        assert result.status == TransferStatus.READY
        assert resumed_store.get_multipart_upload(str(transfer_id)) is None

        async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
            download_client = TransferClient(
                api, resumed_store, http_client=httpx.AsyncClient(timeout=120.0)
            )
            try:
                await download_client.download(result, dest_path)
            finally:
                await download_client.aclose()

        assert dest_path.stat().st_size == _TOTAL_BYTES
        assert _sha256_of(dest_path) == source_sha256
    finally:
        if transfer_id is not None:
            async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
                await api.delete_transfer(transfer_id)
        for open_store in open_stores:
            open_store.connection.close()
        source_path.unlink(missing_ok=True)
        dest_path.unlink(missing_ok=True)
        outbox_path.unlink(missing_ok=True)
