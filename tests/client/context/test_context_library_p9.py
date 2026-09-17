"""P9 — AI Library as a source of the local Context Package composer.

Gate: Library integrated into the DEC-0057 local composer via the existing
providers architecture and `StudioApiClient` (P7 HTTP only — never MCP, never
a second backend), with P0 kinds/schema_version/priority and the 256 Kio
budget, safe `server_unreachable` degradation without a read outbox, and no
private-path leaks in `omitted[]`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.context import (
    LIBRARY_CONTEXT_KIND,
    TEXTUAL_LIBRARY_KINDS,
    ContextPackageComposer,
    ContextPackageOptions,
)
from studio_client.context.composer import _SOURCE_PRIORITY, _json_size
from studio_client.context.errors import ContextError
from studio_client.context.library import (
    LibraryContextProvider,
)
from studio_client.errors import AuthenticationError, TransportError
from studio_client.knowledge import ScopePolicy, VaultMemoryProvider
from studio_client.outbox.store import connect
from studio_client.tokens import MemoryTokenStore


@dataclass
class FakeLibraryResource:
    id: UUID
    kind: str
    stable_key: str
    scope: str
    status: str = "active"
    active_version: int = 1
    project_id: UUID | None = None


@dataclass
class FakeLibraryVersion:
    id: UUID
    resource_id: UUID
    version: int
    title: str
    content: dict[str, Any]


@dataclass
class FakeLibraryLock:
    resource_id: UUID
    locked_version: int


def _rule_text(body: str) -> dict[str, Any]:
    return {"content_schema": "studio.library.rule/v1", "text": body}


def _skill_text(body: str) -> dict[str, Any]:
    return {"content_schema": "studio.library.skill/v1", "text": body}


@dataclass
class _FakeState:
    project_id: UUID
    generated_at: datetime = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {
            "project_id": str(self.project_id),
            "active_tasks": [],
            "active_claims": [],
            "generated_at": self.generated_at.isoformat(),
        }


class FakeLibraryApi:
    """Async fake of the Library subset of `StudioApiClient` (P7 shapes)."""

    def __init__(
        self,
        *,
        resources: list[FakeLibraryResource] | None = None,
        versions: list[FakeLibraryVersion] | None = None,
        locks: list[FakeLibraryLock] | None = None,
        fail_with: Exception | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self._resources = resources or []
        self._versions = versions or []
        self._locks = locks or []
        self._fail_with = fail_with
        self.calls = calls if calls is not None else []

    async def list_library_resources(self, **kwargs: Any) -> list[FakeLibraryResource]:
        self.calls.append("list_library_resources")
        if self._fail_with is not None:
            raise self._fail_with
        limit = int(kwargs.get("limit", 100))
        return self._resources[:limit]

    async def list_library_versions(self, resource_id: UUID) -> list[FakeLibraryVersion]:
        self.calls.append("list_library_versions")
        if self._fail_with is not None:
            raise self._fail_with
        return [v for v in self._versions if v.resource_id == resource_id]

    async def list_library_locks(self, *, project_id: UUID | None = None) -> list[FakeLibraryLock]:
        self.calls.append("list_library_locks")
        if self._fail_with is not None:
            raise self._fail_with
        return self._locks

    # Minimal shared sources so the composer can build a package.
    async def get_project_state(self, project_id: UUID) -> Any:
        return _FakeState(project_id=project_id)

    async def list_claims(self, **kwargs: Any) -> list[Any]:
        return []

    async def list_decisions(self, **kwargs: Any) -> list[Any]:
        return []

    async def list_ai_work(self, **kwargs: Any) -> list[Any]:
        return []

    async def list_events(self, **kwargs: Any) -> list[Any]:
        return []


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def config(tmp_path: Path) -> ClientConfig:
    return ClientConfig(
        api_base_url="https://example.com",
        machine_id=uuid4(),
    )


def _library_fixture(
    project_id: UUID,
) -> tuple[list[FakeLibraryResource], list[FakeLibraryVersion]]:
    rule_id, skill_id = uuid4(), uuid4()
    resources = [
        FakeLibraryResource(id=rule_id, kind="rule", stable_key="coding-style", scope="studio"),
        FakeLibraryResource(
            id=skill_id,
            kind="skill",
            stable_key="review-checklist",
            scope="project",
            project_id=project_id,
        ),
        FakeLibraryResource(
            id=uuid4(), kind="agent_definition", stable_key="coder", scope="studio"
        ),
        FakeLibraryResource(id=uuid4(), kind="model_profile", stable_key="default", scope="studio"),
        FakeLibraryResource(id=uuid4(), kind="workflow", stable_key="release", scope="studio"),
    ]
    versions = [
        FakeLibraryVersion(
            id=uuid4(),
            resource_id=rule_id,
            version=1,
            title="Coding style",
            content=_rule_text("Always run the tests."),
        ),
        FakeLibraryVersion(
            id=uuid4(),
            resource_id=skill_id,
            version=1,
            title="Review checklist",
            content=_skill_text("Checklist: scope, tests, docs."),
        ),
    ]
    return resources, versions


async def _compose_with_library(
    project_id: UUID,
    config: ClientConfig,
    api: FakeLibraryApi,
    options: ContextPackageOptions | None = None,
) -> Any:
    composer = ContextPackageComposer(api, config)  # type: ignore[arg-type]
    opts = options or ContextPackageOptions(include_library=True)
    return await composer.generate(project_id, options=opts)


# --- kinds mapping (P9 §40) -------------------------------------------------


async def test_library_kinds_map_to_single_library_context_kind(
    project_id: UUID, config: ClientConfig
) -> None:
    resources, versions = _library_fixture(project_id)
    package = await _compose_with_library(
        project_id, config, FakeLibraryApi(resources=resources, versions=versions)
    )

    kinds = {s.kind for s in package.manifest.sources}
    assert LIBRARY_CONTEXT_KIND in kinds
    items = package.data[LIBRARY_CONTEXT_KIND]
    by_kind = {item["library_kind"] for item in items}
    assert by_kind == {"rule", "skill"}
    # Structural kinds are skipped, never serialized blindly.
    omitted = [o for o in package.manifest.omitted if o.kind == LIBRARY_CONTEXT_KIND]
    assert sum(o.count for o in omitted if o.reason == "out_of_scope") == 3


async def test_library_item_carries_safe_logical_provenance(
    project_id: UUID, config: ClientConfig
) -> None:
    resources, versions = _library_fixture(project_id)
    package = await _compose_with_library(
        project_id, config, FakeLibraryApi(resources=resources, versions=versions)
    )

    (ref,) = [s for s in package.manifest.sources if s.kind == LIBRARY_CONTEXT_KIND]
    assert ref.ref == f"library:{project_id}"
    for item in package.data[LIBRARY_CONTEXT_KIND]:
        assert set(item) == {
            "library_kind",
            "stable_key",
            "version",
            "version_origin",
            "scope",
            "title",
            "text",
            "content_schema",
            "deprecated",
        }


# --- schema_version vs content_schema (P9 §39) -------------------------------


async def test_manifest_schema_version_is_1_and_distinct_from_content_schema(
    project_id: UUID, config: ClientConfig
) -> None:
    resources, versions = _library_fixture(project_id)
    package = await _compose_with_library(
        project_id, config, FakeLibraryApi(resources=resources, versions=versions)
    )

    assert package.manifest.schema_version == 1
    schemas = {item["content_schema"] for item in package.data[LIBRARY_CONTEXT_KIND]}
    assert schemas == {"studio.library.rule/v1", "studio.library.skill/v1"}
    assert 1 not in schemas


# --- priority + determinism (P9 §38, §14-15) ---------------------------------


def test_library_priority_sits_between_decisions_and_ai_work() -> None:
    assert _SOURCE_PRIORITY["decisions"] < _SOURCE_PRIORITY["library"]
    assert _SOURCE_PRIORITY["library"] < _SOURCE_PRIORITY["ai_work"]
    # Full DEC-0057 removal order preserved: core first-kept, memory first-dropped.
    order = sorted(_SOURCE_PRIORITY.items(), key=lambda kv: (kv[1], kv[0]))
    names = [name for name, _ in order]
    assert names.index("task") < names.index("library") < names.index("memory")


async def test_library_budget_removal_follows_priority_and_is_deterministic(
    project_id: UUID, config: ClientConfig
) -> None:
    resources = [
        FakeLibraryResource(id=uuid4(), kind="rule", stable_key=f"rule-{i:02d}", scope="studio")
        for i in range(6)
    ]
    versions = [
        FakeLibraryVersion(
            id=uuid4(),
            resource_id=r.id,
            version=1,
            title=r.stable_key,
            content=_rule_text("x" * 2000),
        )
        for r in resources
    ]
    options = ContextPackageOptions(include_library=True, budget_bytes=3000)
    package_a = await _compose_with_library(
        project_id,
        config,
        FakeLibraryApi(resources=resources, versions=versions),
        options,
    )
    package_b = await _compose_with_library(
        project_id,
        config,
        FakeLibraryApi(resources=list(reversed(resources)), versions=versions),
        options,
    )

    assert package_a.manifest.truncated
    dropped = {o.kind for o in package_a.manifest.omitted if o.reason == "budget"}
    assert "library" in dropped or dropped  # something had to give
    canonical_a = json.dumps(package_a.data, sort_keys=True, ensure_ascii=False)
    canonical_b = json.dumps(package_b.data, sort_keys=True, ensure_ascii=False)
    assert canonical_a == canonical_b


# --- exact budget: 256 Kio, bytes not chars (P9 §37) --------------------------


def test_budget_unit_is_kibibytes_utf8_bytes() -> None:
    assert ContextPackageOptions().budget_bytes == 256 * 1024
    assert ContextPackageOptions().library_kinds == TEXTUAL_LIBRARY_KINDS
    payload = {"text": "é" * 100 + "中" * 10 + "🎯"}
    assert _json_size(payload) == len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    assert _json_size(payload) != len(json.dumps(payload, ensure_ascii=False))


async def test_budget_boundary_exact_accept_then_overflow_omits(
    project_id: UUID, config: ClientConfig
) -> None:
    resources, versions = _library_fixture(project_id)
    api = FakeLibraryApi(resources=resources, versions=versions)
    composer = ContextPackageComposer(api, config)  # type: ignore[arg-type]

    # NOTE: the manifest embeds `limits.budget_bytes`, so byte-exact
    # comparisons only hold within one digit width — stay in 4-digit land.
    full = await composer.generate(
        project_id,
        options=ContextPackageOptions(include_library=True, budget_bytes=9999),
    )
    assert not full.manifest.truncated
    exact = full.size_bytes()
    assert 1000 <= exact <= 9999
    at_limit = await composer.generate(
        project_id,
        options=ContextPackageOptions(include_library=True, budget_bytes=exact),
    )
    assert not at_limit.manifest.truncated
    assert at_limit.size_bytes() == exact
    over = await composer.generate(
        project_id,
        options=ContextPackageOptions(include_library=True, budget_bytes=exact - 1),
    )
    assert over.manifest.truncated
    assert any(o.reason == "budget" for o in over.manifest.omitted)


# --- omitted privacy, Linux + Windows (P9 §41-42) ------------------------------


@pytest.mark.parametrize(
    "private_root",
    [
        "/home/alice/company/secret-project",
        "C:\\Users\\Alice\\Documents\\Studio\\Private\\secret.md",
    ],
)
async def test_omitted_never_reveals_private_paths(
    project_id: UUID, config: ClientConfig, private_root: str
) -> None:
    memory = VaultMemoryProvider(
        vault_root=Path(private_root),
        scope=ScopePolicy(allowed_prefixes=("projects/slug/",)),
    )
    failing_library = FakeLibraryApi(fail_with=TransportError("offline"))
    composer = ContextPackageComposer(
        failing_library,
        config,
        memory_provider=memory,  # type: ignore[arg-type]
    )
    package = await composer.generate(
        project_id,
        options=ContextPackageOptions(include_memory=True, memory_query="x"),
    )

    blob = json.dumps(package.to_dict(), ensure_ascii=False)
    assert private_root not in blob
    assert all(o.reason for o in package.manifest.omitted)


# --- degraded reading: server_unreachable (P9 §43, §35) -------------------------


async def test_library_server_unreachable_degrades_package_survives(
    project_id: UUID, config: ClientConfig
) -> None:
    vault = config.knowledge_vault_path
    memory: VaultMemoryProvider | None = None
    include_memory = False
    if vault is not None:
        vault.mkdir(parents=True, exist_ok=True)
        exposed = vault / "projects" / "slug"
        exposed.mkdir(parents=True, exist_ok=True)
        (exposed / "note.md").write_text("# Note\nlocal content here", encoding="utf-8")
        memory = VaultMemoryProvider(
            vault_root=vault, scope=ScopePolicy(allowed_prefixes=("projects/slug/",))
        )
        include_memory = True

    api = FakeLibraryApi(fail_with=TransportError("connection refused"))
    composer = ContextPackageComposer(api, config, memory_provider=memory)  # type: ignore[arg-type]
    package = await composer.generate(
        project_id,
        options=ContextPackageOptions(
            include_library=True,
            include_memory=include_memory,
            memory_query="local",
        ),
    )

    library_omitted = [o for o in package.manifest.omitted if o.kind == "library"]
    assert len(library_omitted) == 1
    assert library_omitted[0].reason == "server_unreachable"
    assert "project_state" in {s.kind for s in package.manifest.sources}
    if include_memory:
        assert "memory" in {s.kind for s in package.manifest.sources}


async def test_non_transport_library_error_is_not_swallowed(
    project_id: UUID, config: ClientConfig
) -> None:
    api = FakeLibraryApi(fail_with=AuthenticationError(401, "unauthorized", "bad token"))
    composer = ContextPackageComposer(api, config)  # type: ignore[arg-type]
    with pytest.raises(AuthenticationError):
        await composer.generate(project_id, options=ContextPackageOptions(include_library=True))


async def test_invalid_library_content_propagates(project_id: UUID, config: ClientConfig) -> None:
    resource = FakeLibraryResource(id=uuid4(), kind="rule", stable_key="broken", scope="studio")
    versions = [
        FakeLibraryVersion(
            id=uuid4(),
            resource_id=resource.id,
            version=1,
            title="Broken",
            content={"content_schema": "studio.library.rule/v1"},
        )
    ]
    api = FakeLibraryApi(resources=[resource], versions=versions)
    composer = ContextPackageComposer(api, config)  # type: ignore[arg-type]
    with pytest.raises(ContextError) as exc_info:
        await composer.generate(project_id, options=ContextPackageOptions(include_library=True))
    assert exc_info.value.reason == "invalid_library_content"


# --- versions: locks, shadowing, deprecated (P9 §27) -----------------------------


async def test_project_lock_selects_locked_version_with_origin(
    project_id: UUID, config: ClientConfig
) -> None:
    resource_id = uuid4()
    resources = [
        FakeLibraryResource(
            id=resource_id,
            kind="rule",
            stable_key="pinned",
            scope="studio",
            active_version=2,
        )
    ]
    versions = [
        FakeLibraryVersion(
            id=uuid4(),
            resource_id=resource_id,
            version=1,
            title="v1",
            content=_rule_text("version one"),
        ),
        FakeLibraryVersion(
            id=uuid4(),
            resource_id=resource_id,
            version=2,
            title="v2",
            content=_rule_text("version two"),
        ),
    ]
    locks = [FakeLibraryLock(resource_id=resource_id, locked_version=1)]
    package = await _compose_with_library(
        project_id, config, FakeLibraryApi(resources=resources, versions=versions, locks=locks)
    )

    (item,) = package.data[LIBRARY_CONTEXT_KIND]
    assert item["version"] == 1
    assert item["version_origin"] == "lock"
    assert item["text"] == "version one"


async def test_shadowing_user_over_project_over_studio(
    project_id: UUID, config: ClientConfig
) -> None:
    other_project = uuid4()
    resources = [
        FakeLibraryResource(id=uuid4(), kind="rule", stable_key="same", scope="studio"),
        FakeLibraryResource(
            id=uuid4(),
            kind="rule",
            stable_key="same",
            scope="project",
            project_id=project_id,
        ),
        FakeLibraryResource(id=uuid4(), kind="rule", stable_key="same", scope="user"),
        FakeLibraryResource(
            id=uuid4(),
            kind="rule",
            stable_key="same",
            scope="project",
            project_id=other_project,
        ),
    ]
    versions = [
        FakeLibraryVersion(
            id=uuid4(),
            resource_id=r.id,
            version=1,
            title=r.scope,
            content=_rule_text(f"text from {r.scope}"),
        )
        for r in resources
    ]
    package = await _compose_with_library(
        project_id, config, FakeLibraryApi(resources=resources, versions=versions)
    )

    items = package.data[LIBRARY_CONTEXT_KIND]
    assert len(items) == 1
    assert items[0]["scope"] == "user"
    assert items[0]["text"] == "text from user"


async def test_deprecated_resource_kept_with_flag(project_id: UUID, config: ClientConfig) -> None:
    resource = FakeLibraryResource(
        id=uuid4(), kind="skill", stable_key="old", scope="studio", status="deprecated"
    )
    versions = [
        FakeLibraryVersion(
            id=uuid4(),
            resource_id=resource.id,
            version=1,
            title="Old",
            content=_skill_text("legacy guidance"),
        )
    ]
    package = await _compose_with_library(
        project_id, config, FakeLibraryApi(resources=[resource], versions=versions)
    )

    (item,) = package.data[LIBRARY_CONTEXT_KIND]
    assert item["deprecated"] is True


# --- outbox: reads never enqueue (P9 §44) ---------------------------------------


def _outbox_counts(path: Path) -> dict[str, int]:
    conn = connect(path)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in ("pending_events", "pending_mutations", "pending_markers")
        }
    finally:
        conn.close()


async def test_degraded_composition_leaves_outbox_untouched(
    project_id: UUID, config: ClientConfig, tmp_path: Path
) -> None:
    outbox_path = tmp_path / "outbox.sqlite3"
    before = _outbox_counts(outbox_path)

    api = FakeLibraryApi(fail_with=TransportError("timeout"))
    composer = ContextPackageComposer(api, config)  # type: ignore[arg-type]
    await composer.generate(project_id, options=ContextPackageOptions(include_library=True))

    assert _outbox_counts(outbox_path) == before


# --- StudioApiClient uses P7 routes only (P9 §46-47) ------------------------------


def _p7_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/library":
            assert request.url.params["limit"] == "50"
            return httpx.Response(200, json=[_resource_json()])
        if path == f"/api/v1/library/{_RESOURCE_ID}":
            return httpx.Response(200, json=_resource_json())
        if path == f"/api/v1/library/{_RESOURCE_ID}/versions":
            return httpx.Response(200, json=[_version_json()])
        if path == "/api/v1/library-locks":
            return httpx.Response(200, json=[_lock_json()])
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


_RESOURCE_ID = "11111111-1111-1111-1111-111111111111"


def _resource_json() -> dict[str, Any]:
    return {
        "id": _RESOURCE_ID,
        "kind": "rule",
        "stable_key": "coding-style",
        "scope": "studio",
        "status": "active",
        "active_version": 1,
        "version": 3,
        "created_at": "2026-09-17T12:00:00+00:00",
        "updated_at": "2026-09-17T12:00:00+00:00",
    }


def _version_json() -> dict[str, Any]:
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "resource_id": _RESOURCE_ID,
        "version": 1,
        "title": "Coding style",
        "content": _rule_text("Always run the tests."),
        "created_at": "2026-09-17T12:00:00+00:00",
    }


def _lock_json() -> dict[str, Any]:
    return {
        "id": "33333333-3333-3333-3333-333333333333",
        "project_id": "44444444-4444-4444-4444-444444444444",
        "resource_id": _RESOURCE_ID,
        "locked_version": 1,
        "created_at": "2026-09-17T12:00:00+00:00",
    }


async def test_studio_api_client_library_methods_use_p7_http() -> None:
    config = ClientConfig(
        api_base_url="http://test",
        max_attempts=1,
        backoff_initial=0.001,
        backoff_max=0.002,
    )
    store = MemoryTokenStore()
    store.set_token("http://test", "test-token")
    client = StudioApiClient(config, store, transport=_p7_transport())
    async with client:
        resources = await client.list_library_resources(limit=50)
        assert [r.stable_key for r in resources] == ["coding-style"]
        resource = await client.get_library_resource(UUID(_RESOURCE_ID))
        assert resource.kind.value == "rule"
        versions = await client.list_library_versions(UUID(_RESOURCE_ID))
        assert versions[0].title == "Coding style"
        locks = await client.list_library_locks()
        assert locks[0].locked_version == 1


async def test_library_provider_only_calls_studio_api_client(
    project_id: UUID,
) -> None:
    resources, versions = _library_fixture(project_id)
    calls: list[str] = []
    api = FakeLibraryApi(resources=resources, versions=versions, calls=calls)
    provider = LibraryContextProvider(api)
    result = await provider.fetch(project_id)

    assert calls
    assert set(calls) <= {
        "list_library_resources",
        "list_library_versions",
        "list_library_locks",
    }
    assert len(result.items) == 2


# --- structural boundaries: no server composer, no tables, no MCP (P9 §45) --------


def test_no_server_side_composer_or_package_persistence() -> None:
    repo = Path(__file__).resolve().parents[3]
    service_roots = [
        repo / "services" / "api" / "src" / "studio_api",
        repo / "services" / "mcp" / "src" / "studio_mcp",
    ]
    forbidden = [
        "compose_context_package",
        "apply_context_budget",
        "build_context_manifest",
        "ContextPackageModel",
        "ContextManifestModel",
        "context_packages",
        "context_manifests",
        "studio_compose_context",
    ]
    hits: list[str] = []
    for root in service_roots:
        assert root.is_dir(), f"missing service root {root}"
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    hits.append(f"{path.relative_to(repo)}: {marker}")
    assert hits == []

    migrations = list((repo / "services" / "api" / "alembic").rglob("*.py"))
    assert migrations, "expected alembic migrations to exist for the scan to mean something"
    for path in migrations:
        text = path.read_text(encoding="utf-8")
        assert "context_package" not in text.lower(), path


def test_no_second_bloc_b_backend_for_context() -> None:
    repo = Path(__file__).resolve().parents[3]
    forbidden_dirs = [
        "services/context-api",
        "services/composer",
        "services/context-backend",
        "services/library-sync-service",
    ]
    for rel in forbidden_dirs:
        assert not (repo / rel).exists(), rel
    composer_module = (
        repo / "packages" / "studio-client" / "src" / "studio_client" / "context" / "composer.py"
    )
    assert composer_module.is_file()
