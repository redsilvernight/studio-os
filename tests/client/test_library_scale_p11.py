"""P11-scale: no silent truncation at 100, versions in batch (additive)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from studio_client.context.library import LibraryContextProvider
from studio_client.daemon import skills_bridge
from studio_client.skill_sync import fetch_skill_projections


@dataclass
class _Resource:
    id: UUID
    stable_key: str
    kind: str
    scope: str = "studio"
    status: str = "active"
    active_version: int = 1
    project_id: UUID | None = None


@dataclass
class _Version:
    id: UUID
    resource_id: UUID
    version: int
    title: str
    content: dict[str, object]
    description: str | None = None


@dataclass
class _FakeBatchApi:
    resources: list[_Resource]
    versions: list[_Version]
    calls: list[str]

    async def list_library_resources(
        self,
        *,
        kind: str | None = None,
        limit: int = 500,
        offset: int = 0,
        **_kwargs: Any,
    ) -> list[_Resource]:
        self.calls.append("list_library_resources")
        rows = [r for r in self.resources if kind is None or r.kind == kind]
        return rows[offset : offset + limit]

    async def list_library_locks(self, *, project_id: UUID | None = None) -> list[Any]:
        self.calls.append("list_library_locks")
        return []

    async def list_library_versions(self, resource_id: UUID) -> list[_Version]:  # pragma: no cover
        self.calls.append("list_library_versions")
        return [v for v in self.versions if v.resource_id == resource_id]

    async def list_library_versions_batch(
        self, lookups: list[tuple[UUID, int]]
    ) -> list[_Version]:
        self.calls.append("list_library_versions_batch")
        wanted = {(str(rid), ver) for rid, ver in lookups}
        return [v for v in self.versions if (str(v.resource_id), v.version) in wanted]


def _make_library(n: int) -> tuple[list[_Resource], list[_Version]]:
    resources: list[_Resource] = []
    versions: list[_Version] = []
    for index in range(n):
        rid = uuid4()
        resources.append(_Resource(id=rid, stable_key=f"skill-{index:03d}", kind="skill"))
        versions.append(
            _Version(
                id=uuid4(),
                resource_id=rid,
                version=1,
                title=f"skill-{index:03d}",
                content={
                    "content_schema": "studio.library.skill/v1",
                    "text": f"body {index}",
                },
            )
        )
    return resources, versions


def test_scale_200_skills_no_truncation_constant_requests() -> None:
    resources, versions = _make_library(200)
    calls: list[str] = []
    api = _FakeBatchApi(resources, versions, calls)

    items = asyncio.run(fetch_skill_projections(api, None))

    assert len(items) == 200
    # 1 listing page (500) + 1 locks + 1 batch versions = 3 requests, no N+1.
    assert calls.count("list_library_resources") == 1
    assert calls.count("list_library_locks") == 0  # global sync: no project_id
    assert calls.count("list_library_versions_batch") == 1
    assert "list_library_versions" not in calls


def test_scale_200_effective_versions_single_batch() -> None:
    resources, versions = _make_library(200)
    calls: list[str] = []
    api = _FakeBatchApi(resources, versions, calls)

    rows = asyncio.run(
        LibraryContextProvider(api).fetch_effective_versions(None, kind="skill")
    )

    assert len(rows) == 200
    assert calls.count("list_library_versions_batch") == 1
    assert "list_library_versions" not in calls


def test_scale_bridge_fetch_uses_batch_not_n_plus_1() -> None:
    resources, versions = _make_library(200)
    calls: list[str] = []
    api = _FakeBatchApi(resources, versions, calls)

    result = asyncio.run(skills_bridge.fetch_library_projections(api, None))

    assert len(result) == 200
    assert calls.count("list_library_versions_batch") <= 2
    assert "list_library_versions" not in calls
    # Total HTTP-equivalent calls stay far below the rate-limiter burst (20).
    assert len(calls) <= 5
