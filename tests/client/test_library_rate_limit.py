"""Library sync under a rate limit: bounded version calls, Retry-After, readable 429."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.context.library import LibraryContextProvider
from studio_client.errors import RateLimitError
from studio_client.tokens import MemoryTokenStore

pytestmark = pytest.mark.asyncio

_KINDS = ("rule", "skill")


def _library(count: int = 25) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    resources: list[dict[str, Any]] = []
    versions: dict[str, dict[str, Any]] = {}
    for kind in _KINDS:
        for index in range(count):
            rid = str(uuid4())
            resources.append(
                {
                    "id": rid,
                    "kind": kind,
                    "stable_key": f"{kind}-{index}",
                    "scope": "studio",
                    "status": "active",
                    "active_version": 1,
                    "version": 1,
                    "created_at": "2026-09-17T12:00:00+00:00",
                    "updated_at": "2026-09-17T12:00:00+00:00",
                }
            )
            versions[rid] = {
                "id": str(uuid4()),
                "resource_id": rid,
                "version": 1,
                "title": f"{kind} {index}",
                "description": None,
                "content": {"content_schema": f"studio.library.{kind}/v1", "text": "body"},
                "created_at": "2026-09-17T12:00:00+00:00",
            }
    return resources, versions


def _client(handler: Any, **overrides: Any) -> StudioApiClient:
    params = {
        "api_base_url": "http://test",
        "max_attempts": 3,
        "backoff_initial": 0.001,
        "backoff_max": 5.0,
    }
    params.update(overrides)
    store = MemoryTokenStore()
    store.set_token("http://test", "tok")
    return StudioApiClient(ClientConfig(**params), store, transport=httpx.MockTransport(handler))


def _server(throttle: dict[str, Any] | None = None) -> tuple[Any, dict[str, int]]:
    resources, versions = _library()
    stats = {"versions": 0, "rejected": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/library":
            return httpx.Response(200, json=resources)
        if path.endswith("/versions"):
            rid = path.split("/")[-2]
            if throttle is not None and stats["rejected"] < throttle["times"]:
                stats["rejected"] += 1
                return httpx.Response(
                    429, headers={"Retry-After": str(throttle["retry_after"])}, json={}
                )
            stats["versions"] += 1
            return httpx.Response(200, json=[versions[rid]])
        return httpx.Response(404, json={"detail": "not found"})

    return handler, stats


async def test_bounded_selection_reads_only_the_selected_versions() -> None:
    handler, stats = _server()
    async with _client(handler) as api:
        result = await LibraryContextProvider(api).fetch(
            None, stable_keys={"rule": {"rule-3"}, "skill": {"skill-7", "skill-9"}}
        )
    assert sorted(item.stable_key for item in result.items) == ["rule-3", "skill-7", "skill-9"]
    assert stats["versions"] == 3


async def test_a_provider_never_rereads_a_version_list() -> None:
    handler, stats = _server()
    async with _client(handler) as api:
        provider = LibraryContextProvider(api)
        await provider.fetch(None, kinds=("skill",), stable_keys={"skill": {"skill-1"}})
        await provider.fetch(None, kinds=("skill",), stable_keys={"skill": {"skill-1"}})
    assert stats["versions"] == 1


async def test_temporary_429_waits_retry_after_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("studio_client.api_client.sleep", fake_sleep)
    handler, stats = _server({"times": 2, "retry_after": 2})
    async with _client(handler) as api:
        result = await LibraryContextProvider(api).fetch(
            None, kinds=("rule",), stable_keys={"rule": {"rule-0"}}
        )
    assert [item.stable_key for item in result.items] == ["rule-0"]
    assert waits == [2, 2]
    assert stats["versions"] == 1


async def test_persistent_429_stops_after_the_attempt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("studio_client.api_client.sleep", fake_sleep)
    handler, stats = _server({"times": 999, "retry_after": 1})
    async with _client(handler) as api:
        with pytest.raises(RateLimitError) as exc:
            await LibraryContextProvider(api).fetch(
                None, kinds=("rule",), stable_keys={"rule": {"rule-0", "rule-1"}}
            )
    assert stats["rejected"] == 3
    assert exc.value.retry_after == 1
    assert "retry after 1s" in str(exc.value)


async def test_429_beyond_the_maximum_wait_fails_readably_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(seconds: float) -> None:
        pytest.fail("must not wait beyond the bound")

    monkeypatch.setattr("studio_client.api_client.sleep", no_sleep)
    handler, stats = _server({"times": 999, "retry_after": 120})
    async with _client(handler, backoff_max=5.0) as api:
        with pytest.raises(RateLimitError) as exc:
            await LibraryContextProvider(api).fetch(
                None, kinds=("rule",), stable_keys={"rule": {"rule-0"}}
            )
    assert stats["rejected"] == 1
    assert exc.value.status_code == 429
    assert "retry after 120s" in str(exc.value)
