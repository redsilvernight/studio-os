"""Library version reads through the batch endpoint, with fallback to per-resource reads."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from studio_client.context.library import LibraryContextProvider
from studio_client.errors import RateLimitError

from tests.client.test_library_rate_limit import _client, _library

pytestmark = pytest.mark.asyncio

BATCH = "/api/v1/library/versions/batch-get"


def _server(
    count: int = 60, batch_status: int | None = None
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    resources, versions = _library(count)
    stats: dict[str, Any] = {"batches": [], "units": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/library":
            return httpx.Response(200, json=resources)
        if path == BATCH:
            if batch_status is not None:
                return httpx.Response(batch_status, json={"detail": "nope"})
            refs = json.loads(request.content)["items"]
            stats["batches"].append(len(refs))
            items = [
                {
                    "resource_id": ref["resource_id"],
                    "version": ref["version"],
                    "status": "ok",
                    "detail": versions[ref["resource_id"]],
                }
                for ref in refs
            ]
            return httpx.Response(200, json={"items": items})
        if path.endswith("/versions"):
            stats["units"] += 1
            return httpx.Response(200, json=[versions[path.split("/")[-2]]])
        return httpx.Response(404, json={"detail": "not found"})

    return handler, stats, resources


async def test_n_resources_take_ceil_n_over_max_calls_and_match_the_unit_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("studio_client.context.library.LIBRARY_VERSION_BATCH_MAX", 50)
    handler, stats, _ = _server(count=60)
    async with _client(handler) as api:
        batched = await LibraryContextProvider(api).fetch(None, limit=200)
    assert stats["batches"] == [50, 50, 20]
    assert stats["units"] == 0

    handler, unit_stats, _ = _server(count=60, batch_status=404)
    async with _client(handler) as api:
        unit = await LibraryContextProvider(api).fetch(None, limit=200)
    assert unit_stats["units"] == 120
    assert [i.to_dict() for i in batched.items] == [i.to_dict() for i in unit.items]
    assert batched.skipped == unit.skipped


async def test_default_batch_bound_serves_120_versions_in_one_call() -> None:
    """P11-scale: the bound is 500, so a 60-resource sync is a single batch."""
    handler, stats, _ = _server(count=60)
    async with _client(handler) as api:
        await LibraryContextProvider(api).fetch(None, limit=200)
    assert stats["batches"] == [120]
    assert stats["units"] == 0


@pytest.mark.parametrize("status", [404, 405])
async def test_unsupported_batch_route_falls_back_once(status: int) -> None:
    handler, stats, _ = _server(count=3, batch_status=status)
    async with _client(handler) as api:
        result = await LibraryContextProvider(api).fetch(None)
    assert len(result.items) == 6
    assert stats["units"] == 6


async def test_effective_versions_share_the_batch_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("studio_client.context.library.LIBRARY_VERSION_BATCH_MAX", 50)
    handler, stats, _ = _server(count=60)
    async with _client(handler) as api:
        rows = await LibraryContextProvider(api).fetch_effective_versions(
            None, kind="rule", limit=200
        )
    assert len(rows) == 60
    assert stats["batches"] == [50, 10]
    assert stats["units"] == 0


async def test_batch_rate_limit_stays_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("studio_client.api_client.sleep", no_sleep)
    resources, _ = _library(2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/library":
            return httpx.Response(200, json=resources)
        return httpx.Response(429, headers={"Retry-After": "1"}, json={})

    async with _client(handler) as api:
        with pytest.raises(RateLimitError) as exc:
            await LibraryContextProvider(api).fetch(None)
    assert exc.value.retry_after == 1
