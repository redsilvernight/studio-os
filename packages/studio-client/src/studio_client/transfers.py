from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from studio_contracts.transfers import Transfer, TransferStatus

from studio_client.api_client import StudioApiClient
from studio_client.errors import StudioApiError, TransferError
from studio_client.outbox.models import MultipartUploadState
from studio_client.outbox.store import OutboxStore, transaction

_EXPIRY_SAFETY_MARGIN = timedelta(seconds=60)

_READ_CHUNK_BYTES = 1024 * 1024


def _md5_base64(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return base64.b64encode(digest.digest()).decode()


def _sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TransferClient:
    """Moves file bytes directly to/from MinIO/S3 via presigned URLs that
    `StudioApiClient` hands out — never through the API process (invariant,
    `.claude/rules/storage-transfers.md`). Multipart progress (`upload_id`
    and each completed part's ETag) is persisted in `OutboxStore`'s
    `multipart_uploads` table as each part finishes, so an interrupted
    upload resumes without re-uploading parts already accepted by storage
    (sous-etape 6.7, `docs/ROADMAP_STEP6_BREAKDOWN.md`)."""

    def __init__(
        self,
        api: StudioApiClient,
        store: OutboxStore,
        *,
        http_client: httpx.AsyncClient | None = None,
        part_concurrency: int = 4,
    ) -> None:
        if part_concurrency < 1:
            raise ValueError(f"part_concurrency must be >= 1, got {part_concurrency}")
        self._api = api
        self._store = store
        self._http = http_client or httpx.AsyncClient()
        self._owns_http = http_client is None
        self._part_concurrency = part_concurrency

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def upload(self, transfer: Transfer, file_path: Path) -> Transfer:
        """Idempotent no-op if `transfer` is already `ready`. Raises
        `ValueError` if `file_path`'s real size disagrees with
        `transfer.size_bytes` (the value creation-time quota enforcement
        was computed against, DEC-0019/DEC-0025) rather than silently
        uploading the wrong number of bytes."""
        if transfer.status == TransferStatus.READY:
            return transfer

        actual_size = file_path.stat().st_size
        if actual_size != transfer.size_bytes:
            raise ValueError(
                f"{file_path} is {actual_size} bytes on disk, "
                f"transfer {transfer.id} expects {transfer.size_bytes}"
            )

        state = self._store.get_multipart_upload(str(transfer.id))
        if state is not None:
            return await self._upload_multipart(transfer, file_path, state)

        content_md5: str | None = None
        try:
            response = await self._api.initiate_upload(transfer.id)
        except StudioApiError as exc:
            if exc.error_code != "missing_content_md5":
                raise
            content_md5 = _md5_base64(file_path)
            response = await self._api.initiate_upload(transfer.id, content_md5=content_md5)

        if not response.multipart:
            assert response.upload_url is not None
            assert content_md5 is not None
            return await self._upload_single(transfer, file_path, response.upload_url, content_md5)

        assert response.upload_id is not None
        assert response.part_urls is not None
        assert response.part_size_bytes is not None
        with transaction(self._store.connection):
            self._store.save_multipart_upload(
                str(transfer.id),
                response.upload_id,
                str(file_path),
                response.part_size_bytes,
                response.part_urls,
                response.part_urls_expires_at,
            )
        state = self._store.get_multipart_upload(str(transfer.id))
        assert state is not None
        return await self._upload_multipart(transfer, file_path, state)

    async def _refresh_missing_parts(
        self, transfer: Transfer, part_numbers: list[int]
    ) -> MultipartUploadState:
        """Re-presigns `part_numbers` against storage's own record of what it
        has actually accepted (DEC-0037), merges the result into local
        state, and returns the refreshed state. `unknown_upload_id` means
        storage has abandoned this upload (TTL past the server's retention,
        `studio-admin transfers abort-stale-multipart`) — nothing to resume,
        so local state is purged and the caller must restart via `upload()`."""
        state = self._store.get_multipart_upload(str(transfer.id))
        assert state is not None
        try:
            refreshed = await self._api.refresh_upload_parts(
                transfer.id,
                upload_id=state.upload_id,
                part_size_bytes=state.part_size_bytes,
                part_numbers=part_numbers,
            )
        except StudioApiError as exc:
            if exc.error_code == "unknown_upload_id":
                with transaction(self._store.connection):
                    self._store.delete_multipart_upload(str(transfer.id))
                raise TransferError(
                    f"multipart upload {state.upload_id} for transfer {transfer.id} is no "
                    "longer known to storage — call upload() again to restart it"
                ) from exc
            raise
        with transaction(self._store.connection):
            self._store.update_part_urls(
                str(transfer.id),
                refreshed.part_urls,
                refreshed.expires_at,
                refreshed.uploaded_parts,
            )
        new_state = self._store.get_multipart_upload(str(transfer.id))
        assert new_state is not None
        return new_state

    async def _ensure_fresh_part_urls(
        self, transfer: Transfer, state: MultipartUploadState
    ) -> MultipartUploadState:
        """Proactive refresh before starting/resuming an upload (DEC-0037).
        A missing `part_urls_expires_at` (state saved by an older client
        version, or a response that never carried one) is treated as
        "assume expired" — the safe default, since a stale cached URL fails
        closed as a 403 anyway, just later and after wasted round-trips."""
        pending = [n for n in state.part_urls if n not in state.completed_parts]
        if not pending:
            return state
        expires_at = state.part_urls_expires_at
        if expires_at is not None and datetime.now(UTC) < expires_at - _EXPIRY_SAFETY_MARGIN:
            return state
        return await self._refresh_missing_parts(transfer, pending)

    async def _upload_single(
        self, transfer: Transfer, file_path: Path, upload_url: str, content_md5: str
    ) -> Transfer:
        data = file_path.read_bytes()
        try:
            response = await self._http.put(
                upload_url,
                content=data,
                headers={"Content-Type": transfer.content_type, "Content-MD5": content_md5},
            )
        except httpx.TransportError as exc:
            raise TransferError(
                f"upload to storage failed for transfer {transfer.id}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise TransferError(
                f"upload to storage failed for transfer {transfer.id}: {response.status_code}"
            )
        sha256 = _sha256_hex(file_path)
        return await self._api.complete_upload(transfer.id, size_bytes=len(data), sha256=sha256)

    async def _upload_multipart(
        self, transfer: Transfer, file_path: Path, state: MultipartUploadState
    ) -> Transfer:
        state = await self._ensure_fresh_part_urls(transfer, state)
        part_size = state.part_size_bytes
        pending = [n for n in state.part_urls if n not in state.completed_parts]

        async def _put_part(part_number: int, url: str, chunk: bytes) -> httpx.Response:
            try:
                return await self._http.put(url, content=chunk)
            except httpx.TransportError as exc:
                raise TransferError(
                    f"upload of part {part_number} failed for transfer {transfer.id}: {exc}"
                ) from exc

        async def _upload_part(part_number: int) -> None:
            offset = (part_number - 1) * part_size
            with file_path.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read(part_size)
            response = await _put_part(part_number, state.part_urls[part_number], chunk)
            if response.status_code == 403:
                # One refresh, one retry — a stale/expired URL, not a
                # permanent failure (DEC-0037). Check `completed_parts`
                # first: a part storage's ListParts already has (another
                # writer, or an earlier crashed attempt whose local record
                # was lost) is adopted as-is — its now-stale cached URL in
                # `part_urls` is never reused, refreshed or not.
                refreshed = await self._refresh_missing_parts(transfer, [part_number])
                if part_number in refreshed.completed_parts:
                    return
                refreshed_url = refreshed.part_urls.get(part_number)
                if refreshed_url is None:
                    raise TransferError(
                        f"storage refused part {part_number} for transfer {transfer.id} and "
                        "a refresh produced neither a new URL nor a confirmed upload"
                    )
                response = await _put_part(part_number, refreshed_url, chunk)
            if response.status_code >= 400:
                raise TransferError(
                    f"upload of part {part_number} failed for transfer "
                    f"{transfer.id}: {response.status_code}"
                )
            etag = response.headers.get("ETag", "").strip('"')
            with transaction(self._store.connection):
                self._store.record_completed_part(str(transfer.id), part_number, etag)

        if pending:
            semaphore = asyncio.Semaphore(self._part_concurrency)

            async def _bounded(part_number: int) -> None:
                async with semaphore:
                    await _upload_part(part_number)

            try:
                async with asyncio.TaskGroup() as tg:
                    for part_number in pending:
                        tg.create_task(_bounded(part_number))
            except* TransferError as eg:
                # Parts already accepted by storage before the first failure
                # are already persisted (each `_upload_part` records its own
                # completion) — surfacing one representative error is enough
                # for the caller to retry the whole `upload()` call, which
                # resumes from those completed parts.
                raise eg.exceptions[0] from None

        completed = self._store.get_multipart_upload(str(transfer.id))
        assert completed is not None
        sha256 = _sha256_hex(file_path)
        result = await self._api.complete_upload(
            transfer.id,
            size_bytes=file_path.stat().st_size,
            sha256=sha256,
            upload_id=completed.upload_id,
            parts=completed.completed_parts,
        )
        with transaction(self._store.connection):
            self._store.delete_multipart_upload(str(transfer.id))
        return result

    async def download(self, transfer: Transfer, dest_path: Path) -> None:
        """Resumes from `dest_path`'s existing size via HTTP Range — the
        source of resumable state is the partial file itself, not a
        separate local record. A no-op (beyond a `sha256` check) if
        `dest_path` already holds exactly `transfer.size_bytes`; a local
        file *larger* than expected is not a valid resume point and is
        rejected rather than silently accepted as complete."""
        existing_bytes = dest_path.stat().st_size if dest_path.exists() else 0
        if existing_bytes > transfer.size_bytes:
            raise TransferError(
                f"local file for transfer {transfer.id} is {existing_bytes} bytes, "
                f"larger than the expected {transfer.size_bytes} bytes — not a valid "
                "resume point"
            )
        if existing_bytes == transfer.size_bytes:
            self._verify_sha256(transfer, dest_path)
            return

        download = await self._api.get_download_url(transfer.id)
        headers = {"Range": f"bytes={existing_bytes}-"} if existing_bytes else {}

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with self._http.stream("GET", download.download_url, headers=headers) as response:
                if response.status_code >= 400:
                    raise TransferError(
                        f"download from storage failed for transfer {transfer.id}: "
                        f"{response.status_code}"
                    )
                mode = "ab" if existing_bytes and response.status_code == 206 else "wb"
                with dest_path.open(mode) as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
        except httpx.TransportError as exc:
            raise TransferError(
                f"download from storage failed for transfer {transfer.id}: {exc}"
            ) from exc

        final_size = dest_path.stat().st_size
        if final_size != transfer.size_bytes:
            raise TransferError(
                f"downloaded {final_size} bytes for transfer {transfer.id}, "
                f"expected {transfer.size_bytes}"
            )
        self._verify_sha256(transfer, dest_path)

    def _verify_sha256(self, transfer: Transfer, dest_path: Path) -> None:
        """`transfer.sha256` is the sender's own declared hash, never
        server-verified (`.claude/rules/storage-transfers.md`) — this only
        catches a local file whose *content* silently diverged from what the
        sender meant to send, on top of the size check already done by the
        caller. A missing `sha256` (multipart uploads don't get one, DEC-0025)
        skips this check entirely rather than failing closed."""
        if transfer.sha256 is None:
            return
        actual = _sha256_hex(dest_path)
        if actual != transfer.sha256:
            raise TransferError(
                f"downloaded file for transfer {transfer.id} has sha256 {actual}, "
                f"expected {transfer.sha256} (sender-declared, not server-verified)"
            )
