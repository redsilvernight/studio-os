from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.errors import TransferError
from studio_client.outbox import OutboxStore, connect
from studio_client.tokens import MemoryTokenStore
from studio_client.transfers import TransferClient
from studio_contracts.transfers import Transfer, TransferCategory, TransferStatus


def _config() -> ClientConfig:
    return ClientConfig(
        api_base_url="http://test",
        max_attempts=1,
        backoff_initial=0.001,
        backoff_max=0.002,
    )


def _token_store() -> MemoryTokenStore:
    store = MemoryTokenStore()
    store.set_token("http://test", "test-token")
    return store


def _transfer(**overrides: Any) -> Transfer:
    params: dict[str, Any] = {
        "id": uuid4(),
        "transfer_code": "TRF-TEST",
        "sender_user_id": uuid4(),
        "category": TransferCategory.TEMPORARY,
        "filename": "file.bin",
        "object_key": "studio/proj/2026/09/x/file.bin",
        "content_type": "application/octet-stream",
        "size_bytes": 25,
        "status": TransferStatus.CREATED,
        "created_at": datetime.now(UTC),
    }
    params.update(overrides)
    return Transfer.model_validate(params)


def _api_client(handler: Any) -> StudioApiClient:
    return StudioApiClient(_config(), _token_store(), transport=httpx.MockTransport(handler))


def _store(tmp_path: Path) -> OutboxStore:
    return OutboxStore(connect(tmp_path / "outbox.sqlite3"))


def _future_expiry() -> str:
    """A real server's `initiate` always sets `part_urls_expires_at`
    (DEC-0037) — mocks simulating an unremarkable initiate response use this
    so `_ensure_fresh_part_urls`'s "unknown expiry -> assume expired"
    fallback doesn't fire and add an unexpected refresh-parts call; tests
    exercising that fallback set the field to a past timestamp (or omit it)
    deliberately."""
    return (datetime.now(UTC) + timedelta(minutes=10)).isoformat()


def test_transfer_client_rejects_non_positive_part_concurrency(tmp_path: Path) -> None:
    store = _store(tmp_path)
    api = StudioApiClient(_config(), _token_store())
    with pytest.raises(ValueError, match="part_concurrency"):
        TransferClient(api, store, part_concurrency=0)


async def test_upload_small_file_retries_initiate_with_md5(tmp_path: Path) -> None:
    file_path = tmp_path / "small.bin"
    file_path.write_bytes(b"x" * 25)
    transfer = _transfer(size_bytes=25)
    initiate_calls: list[dict[str, Any] | None] = []
    put_seen: dict[str, str] = {}

    def api_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/initiate"):
            body = json.loads(request.content) if request.content else None
            initiate_calls.append(body)
            if not body or not body.get("content_md5"):
                return httpx.Response(422, json={"detail": {"error_code": "missing_content_md5"}})
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "multipart": False,
                    "upload_url": "http://storage.test/put",
                },
            )
        if request.url.path.endswith("/upload/complete"):
            data = transfer.model_dump(mode="json")
            data["status"] = "ready"
            return httpx.Response(200, json=data)
        raise AssertionError(f"unexpected call: {request.url}")

    def storage_handler(request: httpx.Request) -> httpx.Response:
        put_seen["content_md5"] = request.headers.get("content-md5", "")
        put_seen["content_type"] = request.headers.get("content-type", "")
        put_seen["body"] = request.content.decode()
        return httpx.Response(200)

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            result = await client.upload(transfer, file_path)
        finally:
            await client.aclose()

    assert result.status == TransferStatus.READY
    assert len(initiate_calls) == 2
    assert initiate_calls[0] == {"content_md5": None}
    assert initiate_calls[1]["content_md5"]
    assert put_seen["content_md5"] == initiate_calls[1]["content_md5"]
    assert put_seen["content_type"] == transfer.content_type
    assert put_seen["body"] == "x" * 25


async def test_upload_already_ready_is_a_noop(tmp_path: Path) -> None:
    transfer = _transfer(status=TransferStatus.READY)

    def api_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no API call expected for an already-ready transfer")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(api, store, http_client=httpx.AsyncClient())
        try:
            result = await client.upload(transfer, tmp_path / "unused.bin")
        finally:
            await client.aclose()

    assert result is transfer


async def test_upload_size_mismatch_raises_before_any_call(tmp_path: Path) -> None:
    file_path = tmp_path / "small.bin"
    file_path.write_bytes(b"x" * 10)
    transfer = _transfer(size_bytes=25)

    def api_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no API call expected on a local size mismatch")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(api, store, http_client=httpx.AsyncClient())
        try:
            with pytest.raises(ValueError, match="25"):
                await client.upload(transfer, file_path)
        finally:
            await client.aclose()


async def test_upload_multipart_resumes_after_interrupted_part(tmp_path: Path) -> None:
    file_path = tmp_path / "big.bin"
    file_path.write_bytes(b"A" * 10 + b"B" * 10 + b"C" * 5)
    transfer = _transfer(size_bytes=25)
    initiate_call_count = {"n": 0}
    complete_calls: list[dict[str, Any]] = []
    part_attempts: dict[str, int] = {"1": 0, "2": 0, "3": 0}

    def api_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/initiate"):
            initiate_call_count["n"] += 1
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "multipart": True,
                    "upload_id": "upload-1",
                    "part_urls": {
                        1: "http://storage.test/part1",
                        2: "http://storage.test/part2",
                        3: "http://storage.test/part3",
                    },
                    "part_size_bytes": 10,
                    "part_urls_expires_at": _future_expiry(),
                },
            )
        if request.url.path.endswith("/upload/complete"):
            body = json.loads(request.content)
            complete_calls.append(body)
            data = transfer.model_dump(mode="json")
            data["status"] = "ready"
            return httpx.Response(200, json=data)
        raise AssertionError(f"unexpected call: {request.url}")

    def storage_handler(request: httpx.Request) -> httpx.Response:
        part = request.url.path.removeprefix("/part")
        part_attempts[part] += 1
        if part == "3" and part_attempts[part] == 1:
            return httpx.Response(500)
        return httpx.Response(200, headers={"ETag": f'"etag-{part}"'})

    store = _store(tmp_path)

    async def _run_upload() -> Transfer:
        async with _api_client(api_handler) as api:
            client = TransferClient(
                api,
                store,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
            )
            try:
                return await client.upload(transfer, file_path)
            finally:
                await client.aclose()

    with pytest.raises(TransferError):
        await _run_upload()

    state = store.get_multipart_upload(str(transfer.id))
    assert state is not None
    assert set(state.completed_parts) == {1, 2}

    result = await _run_upload()

    assert result.status == TransferStatus.READY
    assert initiate_call_count["n"] == 1
    assert part_attempts == {"1": 1, "2": 1, "3": 2}
    assert complete_calls[0]["parts"] == {"1": "etag-1", "2": "etag-2", "3": "etag-3"}
    assert store.get_multipart_upload(str(transfer.id)) is None


async def test_upload_multipart_network_failure_raises_transfer_error(tmp_path: Path) -> None:
    """A real, *persistent* connection failure (not an HTTP error response)
    must still surface as `TransferError`, not a raw `httpx.TransportError`/
    `ExceptionGroup` leaking out of the internal `TaskGroup` — even though
    DEC-0037 now treats a transport-level failure on the first attempt the
    same as a 403 (one refresh, one retry): the retry hits the same broken
    connection and the error still propagates, it isn't swallowed or
    retried a second time."""
    file_path = tmp_path / "big.bin"
    file_path.write_bytes(b"A" * 10 + b"B" * 10 + b"C" * 5)
    transfer = _transfer(size_bytes=25)
    refresh_calls: list[dict[str, Any]] = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/initiate"):
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "multipart": True,
                    "upload_id": "upload-1",
                    "part_urls": {
                        1: "http://storage.test/part1",
                        2: "http://storage.test/part2",
                        3: "http://storage.test/part3",
                    },
                    "part_size_bytes": 10,
                    "part_urls_expires_at": _future_expiry(),
                },
            )
        if request.url.path.endswith("/upload/refresh-parts"):
            body = json.loads(request.content)
            refresh_calls.append(body)
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "upload_id": "upload-1",
                    "part_size_bytes": 10,
                    "part_urls": {n: f"http://storage.test/part{n}" for n in body["part_numbers"]},
                    "uploaded_parts": {},
                    "expires_at": _future_expiry(),
                },
            )
        raise AssertionError(f"unexpected call: {request.url}")

    def storage_handler(request: httpx.Request) -> httpx.Response:
        part = request.url.path.removeprefix("/part")
        if part == "3":
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, headers={"ETag": f'"etag-{part}"'})

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            with pytest.raises(TransferError):
                await client.upload(transfer, file_path)
        finally:
            await client.aclose()

    assert refresh_calls == [{"upload_id": "upload-1", "part_size_bytes": 10, "part_numbers": [3]}]
    state = store.get_multipart_upload(str(transfer.id))
    assert state is not None
    assert set(state.completed_parts) == {1, 2}


async def test_upload_multipart_resume_proactively_refreshes_expired_urls(
    tmp_path: Path,
) -> None:
    """DEC-0037: resuming against locally-cached part URLs whose TTL has
    already passed (the whole point of a resume long after an interruption)
    must refresh before attempting any PUT, not fail closed against storage
    with a doomed request."""
    file_path = tmp_path / "big.bin"
    file_path.write_bytes(b"A" * 10 + b"B" * 10)
    transfer = _transfer(size_bytes=20)
    refresh_calls: list[dict[str, Any]] = []

    store = _store(tmp_path)
    store.save_multipart_upload(
        str(transfer.id),
        "upload-1",
        str(file_path),
        10,
        {1: "http://storage.test/part1-stale", 2: "http://storage.test/part2-stale"},
        datetime.now(UTC) - timedelta(minutes=5),
    )

    def api_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/refresh-parts"):
            body = json.loads(request.content)
            refresh_calls.append(body)
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "upload_id": "upload-1",
                    "part_size_bytes": 10,
                    "part_urls": {
                        n: f"http://storage.test/part{n}-fresh" for n in body["part_numbers"]
                    },
                    "uploaded_parts": {},
                    "expires_at": _future_expiry(),
                },
            )
        if request.url.path.endswith("/upload/complete"):
            data = transfer.model_dump(mode="json")
            data["status"] = "ready"
            return httpx.Response(200, json=data)
        raise AssertionError(f"unexpected call: {request.url}")

    def storage_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("-stale"):
            raise AssertionError(f"must not PUT a known-stale URL: {request.url}")
        part = request.url.path.removeprefix("/part").removesuffix("-fresh")
        return httpx.Response(200, headers={"ETag": f'"etag-{part}"'})

    async with _api_client(api_handler) as api:
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
            part_concurrency=1,
        )
        try:
            result = await client.upload(transfer, file_path)
        finally:
            await client.aclose()

    assert result.status == TransferStatus.READY
    assert len(refresh_calls) == 1
    assert set(refresh_calls[0]["part_numbers"]) == {1, 2}
    assert store.get_multipart_upload(str(transfer.id)) is None


async def test_upload_multipart_reactive_refresh_retries_403_part(tmp_path: Path) -> None:
    """DEC-0037: even with a locally-fresh expiry (clock drift, or a TTL
    shorter than assumed), a 403 from storage on the actual PUT must trigger
    exactly one refresh-and-retry rather than failing the whole upload."""
    file_path = tmp_path / "big.bin"
    file_path.write_bytes(b"A" * 10)
    transfer = _transfer(size_bytes=10)
    refresh_calls: list[dict[str, Any]] = []
    put_attempts: dict[str, int] = {"stale": 0, "fresh": 0}

    def api_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/initiate"):
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "multipart": True,
                    "upload_id": "upload-1",
                    "part_urls": {1: "http://storage.test/part1-stale"},
                    "part_size_bytes": 10,
                    "part_urls_expires_at": _future_expiry(),
                },
            )
        if request.url.path.endswith("/upload/refresh-parts"):
            body = json.loads(request.content)
            refresh_calls.append(body)
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "upload_id": "upload-1",
                    "part_size_bytes": 10,
                    "part_urls": {1: "http://storage.test/part1-fresh"},
                    "uploaded_parts": {},
                    "expires_at": _future_expiry(),
                },
            )
        if request.url.path.endswith("/upload/complete"):
            data = transfer.model_dump(mode="json")
            data["status"] = "ready"
            return httpx.Response(200, json=data)
        raise AssertionError(f"unexpected call: {request.url}")

    def storage_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("-stale"):
            put_attempts["stale"] += 1
            return httpx.Response(403, text="expired presigned URL")
        put_attempts["fresh"] += 1
        return httpx.Response(200, headers={"ETag": '"etag-1"'})

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
            part_concurrency=1,
        )
        try:
            result = await client.upload(transfer, file_path)
        finally:
            await client.aclose()

    assert result.status == TransferStatus.READY
    assert put_attempts == {"stale": 1, "fresh": 1}
    assert refresh_calls == [{"upload_id": "upload-1", "part_size_bytes": 10, "part_numbers": [1]}]


async def test_upload_multipart_refresh_adopts_server_confirmed_part(tmp_path: Path) -> None:
    """DEC-0037: a part that storage's own `ListParts` already has (the
    local write of `record_completed_part` was lost, e.g. a crash right
    after a successful PUT) must be adopted from the refresh response, never
    re-uploaded."""
    file_path = tmp_path / "big.bin"
    file_path.write_bytes(b"A" * 10)
    transfer = _transfer(size_bytes=10)
    put_attempts = {"n": 0}

    def api_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/initiate"):
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "multipart": True,
                    "upload_id": "upload-1",
                    "part_urls": {1: "http://storage.test/part1-stale"},
                    "part_size_bytes": 10,
                    "part_urls_expires_at": _future_expiry(),
                },
            )
        if request.url.path.endswith("/upload/refresh-parts"):
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "upload_id": "upload-1",
                    "part_size_bytes": 10,
                    "part_urls": {},
                    "uploaded_parts": {1: "etag-already-there"},
                    "expires_at": _future_expiry(),
                },
            )
        if request.url.path.endswith("/upload/complete"):
            body = json.loads(request.content)
            assert body["parts"] == {"1": "etag-already-there"}
            data = transfer.model_dump(mode="json")
            data["status"] = "ready"
            return httpx.Response(200, json=data)
        raise AssertionError(f"unexpected call: {request.url}")

    def storage_handler(request: httpx.Request) -> httpx.Response:
        put_attempts["n"] += 1
        return httpx.Response(403, text="expired presigned URL")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            result = await client.upload(transfer, file_path)
        finally:
            await client.aclose()

    assert result.status == TransferStatus.READY
    assert put_attempts["n"] == 1  # the one rejected attempt, never a retry for this part


async def test_upload_multipart_unknown_upload_id_purges_local_state(tmp_path: Path) -> None:
    """DEC-0037: `409 unknown_upload_id` means storage has abandoned this
    upload (past `studio-admin transfers abort-stale-multipart`'s
    retention) — never a data loss, but local state must be purged so the
    next `upload()` call starts a genuinely fresh `initiate` instead of
    looping on a dead `upload_id`."""
    file_path = tmp_path / "big.bin"
    file_path.write_bytes(b"A" * 10)
    transfer = _transfer(size_bytes=10)

    store = _store(tmp_path)
    store.save_multipart_upload(
        str(transfer.id),
        "upload-dead",
        str(file_path),
        10,
        {1: "http://storage.test/part1-stale"},
        datetime.now(UTC) - timedelta(minutes=5),
    )

    def api_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/refresh-parts"):
            return httpx.Response(409, json={"detail": {"error_code": "unknown_upload_id"}})
        raise AssertionError(f"unexpected call: {request.url}")

    async with _api_client(api_handler) as api:
        client = TransferClient(api, store, http_client=httpx.AsyncClient())
        try:
            with pytest.raises(TransferError, match="no longer known to storage"):
                await client.upload(transfer, file_path)
        finally:
            await client.aclose()

    assert store.get_multipart_upload(str(transfer.id)) is None


async def test_download_full_file_no_range_header(tmp_path: Path) -> None:
    transfer = _transfer(size_bytes=5)
    dest = tmp_path / "out.bin"
    seen: dict[str, str] = {}

    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transfer_id": str(transfer.id),
                "download_url": "http://storage.test/get",
                "expires_at": datetime.now(UTC).isoformat(),
            },
        )

    def storage_handler(request: httpx.Request) -> httpx.Response:
        seen["range"] = request.headers.get("range", "")
        return httpx.Response(200, content=b"hello")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            await client.download(transfer, dest)
        finally:
            await client.aclose()

    assert seen["range"] == ""
    assert dest.read_bytes() == b"hello"


async def test_download_resumes_with_range_header(tmp_path: Path) -> None:
    transfer = _transfer(size_bytes=5)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"he")
    seen: dict[str, str] = {}

    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transfer_id": str(transfer.id),
                "download_url": "http://storage.test/get",
                "expires_at": datetime.now(UTC).isoformat(),
            },
        )

    def storage_handler(request: httpx.Request) -> httpx.Response:
        seen["range"] = request.headers.get("range", "")
        return httpx.Response(206, content=b"llo")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            await client.download(transfer, dest)
        finally:
            await client.aclose()

    assert seen["range"] == "bytes=2-"
    assert dest.read_bytes() == b"hello"


async def test_download_already_complete_is_a_noop(tmp_path: Path) -> None:
    transfer = _transfer(size_bytes=5)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"hello")

    def api_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no API call expected when the file is already complete")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(api, store, http_client=httpx.AsyncClient())
        try:
            await client.download(transfer, dest)
        finally:
            await client.aclose()

    assert dest.read_bytes() == b"hello"


async def test_upload_single_file_expired_url_raises_transfer_error(tmp_path: Path) -> None:
    """TECH/10_TEST_ACCEPTANCE.md scenario 'URL signee expiree': storage
    rejecting a presigned PUT with 403 (what a real expired SigV4 URL gets
    from MinIO, confirmed against real infra in
    `tests/api/test_transfers_expired_url.py`) must surface as `TransferError`,
    not an unhandled `httpx.HTTPStatusError` or a silent `ready` transfer."""
    file_path = tmp_path / "small.bin"
    file_path.write_bytes(b"x" * 25)
    transfer = _transfer(size_bytes=25)

    def api_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload/initiate"):
            body = json.loads(request.content) if request.content else None
            if not body or not body.get("content_md5"):
                return httpx.Response(422, json={"detail": {"error_code": "missing_content_md5"}})
            return httpx.Response(
                200,
                json={
                    "transfer_id": str(transfer.id),
                    "multipart": False,
                    "upload_url": "http://storage.test/put",
                },
            )
        raise AssertionError(f"unexpected call: {request.url}")

    def storage_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<Error><Code>AccessDenied</Code></Error>")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            with pytest.raises(TransferError, match="403"):
                await client.upload(transfer, file_path)
        finally:
            await client.aclose()


async def test_download_expired_url_raises_transfer_error(tmp_path: Path) -> None:
    transfer = _transfer(size_bytes=5)
    dest = tmp_path / "out.bin"

    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transfer_id": str(transfer.id),
                "download_url": "http://storage.test/get",
                "expires_at": datetime.now(UTC).isoformat(),
            },
        )

    def storage_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<Error><Code>AccessDenied</Code></Error>")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            with pytest.raises(TransferError, match="403"):
                await client.download(transfer, dest)
        finally:
            await client.aclose()

    assert not dest.exists() or dest.stat().st_size == 0


async def test_download_size_mismatch_raises_transfer_error(tmp_path: Path) -> None:
    transfer = _transfer(size_bytes=10)
    dest = tmp_path / "out.bin"

    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transfer_id": str(transfer.id),
                "download_url": "http://storage.test/get",
                "expires_at": datetime.now(UTC).isoformat(),
            },
        )

    def storage_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"short")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            with pytest.raises(TransferError, match="expected 10"):
                await client.download(transfer, dest)
        finally:
            await client.aclose()


async def test_download_oversized_local_file_raises_transfer_error(tmp_path: Path) -> None:
    transfer = _transfer(size_bytes=5)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"way too much data")

    def api_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no API call expected: oversized local file is rejected up front")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(api, store, http_client=httpx.AsyncClient())
        try:
            with pytest.raises(TransferError, match="larger than"):
                await client.download(transfer, dest)
        finally:
            await client.aclose()


async def test_download_already_complete_wrong_content_raises_transfer_error(
    tmp_path: Path,
) -> None:
    """Same size as declared, but a different sha256 — DEC-0033's known gap:
    a same-size/different-content local file must not be accepted as done."""
    content = b"hello"
    wrong_content = b"olleh"
    assert len(content) == len(wrong_content)
    transfer = _transfer(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    dest = tmp_path / "out.bin"
    dest.write_bytes(wrong_content)

    def api_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no API call expected when the file is already the right size")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(api, store, http_client=httpx.AsyncClient())
        try:
            with pytest.raises(TransferError, match="sha256"):
                await client.download(transfer, dest)
        finally:
            await client.aclose()


async def test_download_already_complete_with_matching_sha256_is_a_noop(tmp_path: Path) -> None:
    content = b"hello"
    transfer = _transfer(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    dest = tmp_path / "out.bin"
    dest.write_bytes(content)

    def api_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no API call expected when the file is already complete")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(api, store, http_client=httpx.AsyncClient())
        try:
            await client.download(transfer, dest)
        finally:
            await client.aclose()

    assert dest.read_bytes() == content


async def test_download_already_complete_without_sha256_skips_verification(
    tmp_path: Path,
) -> None:
    """No `sha256` on the transfer (e.g. a multipart upload, DEC-0025) — the
    no-op path must not fail closed just because there's nothing to check."""
    transfer = _transfer(size_bytes=5, sha256=None)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"hello")

    def api_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no API call expected when the file is already complete")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(api, store, http_client=httpx.AsyncClient())
        try:
            await client.download(transfer, dest)
        finally:
            await client.aclose()

    assert dest.read_bytes() == b"hello"


async def test_download_fresh_verifies_sha256_after_success(tmp_path: Path) -> None:
    content = b"hello"
    transfer = _transfer(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    dest = tmp_path / "out.bin"

    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transfer_id": str(transfer.id),
                "download_url": "http://storage.test/get",
                "expires_at": datetime.now(UTC).isoformat(),
            },
        )

    def storage_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            await client.download(transfer, dest)
        finally:
            await client.aclose()

    assert dest.read_bytes() == content


async def test_download_fresh_sha256_mismatch_raises_transfer_error(tmp_path: Path) -> None:
    transfer = _transfer(size_bytes=5, sha256=hashlib.sha256(b"hello").hexdigest())
    dest = tmp_path / "out.bin"

    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transfer_id": str(transfer.id),
                "download_url": "http://storage.test/get",
                "expires_at": datetime.now(UTC).isoformat(),
            },
        )

    def storage_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"wrong")

    async with _api_client(api_handler) as api:
        store = _store(tmp_path)
        client = TransferClient(
            api,
            store,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(storage_handler)),
        )
        try:
            with pytest.raises(TransferError, match="sha256"):
                await client.download(transfer, dest)
        finally:
            await client.aclose()
