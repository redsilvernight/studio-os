from __future__ import annotations

import json
from datetime import UTC, datetime
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
    """A real connection failure (not an HTTP error response) must still
    surface as `TransferError`, not a raw `httpx.TransportError`/
    `ExceptionGroup` leaking out of the internal `TaskGroup`."""
    file_path = tmp_path / "big.bin"
    file_path.write_bytes(b"A" * 10 + b"B" * 10 + b"C" * 5)
    transfer = _transfer(size_bytes=25)

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

    state = store.get_multipart_upload(str(transfer.id))
    assert state is not None
    assert set(state.completed_parts) == {1, 2}


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
