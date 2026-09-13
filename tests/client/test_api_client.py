from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.errors import (
    AuthenticationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    QuotaError,
    ServerError,
)
from studio_client.tokens import MemoryTokenStore, MissingMachineToken
from studio_contracts.tasks import TaskCreate


def _config(**overrides: Any) -> ClientConfig:
    params: dict[str, Any] = {
        "api_base_url": "http://test",
        "max_attempts": 3,
        "backoff_initial": 0.001,
        "backoff_max": 0.002,
    }
    params.update(overrides)
    return ClientConfig(**params)


def _token_store(token: str = "test-token") -> MemoryTokenStore:
    store = MemoryTokenStore()
    store.set_token("http://test", token)
    return store


async def test_injects_auth_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=[])

    async with StudioApiClient(
        _config(), _token_store("secret-abc"), transport=httpx.MockTransport(handler)
    ) as client:
        await client.list_projects()

    assert seen["authorization"] == "Bearer secret-abc"


async def test_healthz_is_unauthenticated() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"status": "ok"})

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        result = await client.healthz()

    assert result == {"status": "ok"}
    assert seen["authorization"] == ""


async def test_missing_token_raises_before_any_request() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=[])

    async with StudioApiClient(
        _config(), MemoryTokenStore(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(MissingMachineToken):
            await client.list_projects()

    assert calls["n"] == 0


async def test_create_task_propagates_idempotency_key() -> None:
    seen: dict[str, str] = {}
    project_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        seen["idempotency_key"] = request.headers.get("idempotency-key", "")
        return httpx.Response(
            201,
            json={
                "id": str(uuid4()),
                "readable_id": None,
                "project_id": str(project_id),
                "title": "t",
                "description": None,
                "status": "created",
                "claimed_by_machine_id": None,
                "claimed_by_agent_id": None,
                "version": 1,
                "created_at": "2026-09-13T00:00:00Z",
                "updated_at": "2026-09-13T00:00:00Z",
            },
        )

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        task = await client.create_task(
            TaskCreate(project_id=project_id, title="t"), idempotency_key="key-123"
        )

    assert seen["idempotency_key"] == "key-123"
    assert task.title == "t"


@pytest.mark.parametrize(
    ("status_code", "detail", "expected_type", "expected_error_code"),
    [
        (401, "invalid or revoked machine token", AuthenticationError, None),
        (403, "insufficient role", ForbiddenError, None),
        (404, "task not found", NotFoundError, None),
        (409, {"error_code": "version_conflict"}, ConflictError, "version_conflict"),
        (413, {"error_code": "transfer_too_large"}, QuotaError, "transfer_too_large"),
        (507, {"error_code": "quota_exceeded"}, QuotaError, "quota_exceeded"),
    ],
)
async def test_maps_status_codes_to_typed_errors(
    status_code: int,
    detail: object,
    expected_type: type[Exception],
    expected_error_code: str | None,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"detail": detail})

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(expected_type) as excinfo:
            await client.list_projects()

    if expected_error_code is not None:
        assert isinstance(excinfo.value, ConflictError | QuotaError)
        assert excinfo.value.error_code == expected_error_code


async def test_quota_error_computes_remaining_bytes_from_server_detail() -> None:
    """The server's `quota_exceeded` detail carries `quota_bytes`/
    `consumed_bytes`, never a `remaining_bytes` key directly
    (`services/api/src/studio_api/services/transfers.py`)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            507,
            json={
                "detail": {
                    "error_code": "quota_exceeded",
                    "project_id": str(uuid4()),
                    "consumed_bytes": 90,
                    "requested_bytes": 20,
                    "quota_bytes": 100,
                }
            },
        )

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(QuotaError) as excinfo:
            await client.list_projects()

    assert excinfo.value.remaining_bytes == 10


async def test_quota_error_remaining_bytes_none_when_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(413, json={"detail": {"error_code": "transfer_too_large"}})

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(QuotaError) as excinfo:
            await client.list_projects()

    assert excinfo.value.remaining_bytes is None


async def test_retries_idempotency_key_in_progress_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(
                409, json={"detail": {"error_code": "idempotency_key_in_progress"}}
            )
        return httpx.Response(200, json=[])

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        result = await client.list_projects()

    assert result == []
    assert calls["n"] == 2


async def test_does_not_retry_business_conflict() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(409, json={"detail": {"error_code": "version_conflict"}})

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ConflictError):
            await client.list_projects()

    assert calls["n"] == 1


async def test_retries_server_error_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json=[])

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        result = await client.list_projects()

    assert result == []
    assert calls["n"] == 2


async def test_retries_transport_error_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=[])

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        result = await client.list_projects()

    assert result == []
    assert calls["n"] == 2


async def test_exhausts_retry_budget_then_raises() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"detail": "boom"})

    async with StudioApiClient(
        _config(max_attempts=2), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ServerError):
            await client.list_projects()

    assert calls["n"] == 2


async def test_non_idempotent_write_is_never_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"detail": "boom"})

    async with StudioApiClient(
        _config(), _token_store(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ServerError):
            await client._request("POST", "/api/v1/tasks", json={}, idempotent=False)

    assert calls["n"] == 1


async def test_token_never_appears_in_exception_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid or revoked machine token"})

    async with StudioApiClient(
        _config(), _token_store("super-secret-token"), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AuthenticationError) as excinfo:
            await client.list_projects()

    assert "super-secret-token" not in str(excinfo.value)
    assert "super-secret-token" not in repr(excinfo.value)
