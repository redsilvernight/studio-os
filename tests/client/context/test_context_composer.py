from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.context import ContextPackageComposer, ContextPackageOptions
from studio_client.context.composer import _json_size
from studio_client.errors import TransportError
from studio_client.knowledge import GraphifyGraphProvider, ScopePolicy, VaultMemoryProvider


@dataclass
class FakeModel:
    """Minimal stand-in for Pydantic contract models."""

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return asdict(self)


@dataclass
class FakeTask(FakeModel):
    id: UUID
    title: str
    project_id: UUID


@dataclass
class FakeProjectState(FakeModel):
    project_id: UUID
    active_tasks: list[dict[str, Any]]
    active_claims: list[dict[str, Any]]
    generated_at: datetime


@dataclass
class FakeClaim(FakeModel):
    id: UUID
    project_id: UUID
    resource_path: str


@dataclass
class FakeDecision(FakeModel):
    id: UUID
    title: str


@dataclass
class FakeAIWork(FakeModel):
    id: UUID
    summary: str


@dataclass
class FakeEvent(FakeModel):
    event_id: UUID
    event_type: str
    server_timestamp: datetime
    schema_version: int = 1


class FakeApiClient:
    """Async fake for `StudioApiClient` with controllable responses."""

    def __init__(
        self,
        *,
        task: FakeTask | None = None,
        state: FakeProjectState | None = None,
        claims: list[FakeClaim] | None = None,
        decisions: list[FakeDecision] | None = None,
        ai_work: list[FakeAIWork] | None = None,
        events: list[FakeEvent] | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        self._task = task
        self._state = state
        self._claims = claims or []
        self._decisions = decisions or []
        self._ai_work = ai_work or []
        self._events = events or []
        self._fail_with = fail_with

    async def get_task(self, task_id: UUID) -> FakeTask:
        if self._fail_with:
            raise self._fail_with
        if self._task is None:
            raise RuntimeError("no task")
        return self._task

    async def get_project_state(self, project_id: UUID) -> FakeProjectState:
        if self._fail_with:
            raise self._fail_with
        if self._state is None:
            raise RuntimeError("no state")
        return self._state

    async def list_claims(self, *, project_id: UUID | None = None) -> list[FakeClaim]:
        if self._fail_with:
            raise self._fail_with
        return self._claims

    async def list_decisions(self, *, project_id: UUID | None = None) -> list[FakeDecision]:
        if self._fail_with:
            raise self._fail_with
        return self._decisions

    async def list_ai_work(
        self, *, project_id: UUID | None = None, task_id: UUID | None = None
    ) -> list[FakeAIWork]:
        if self._fail_with:
            raise self._fail_with
        return self._ai_work

    async def list_events(
        self,
        *,
        project_id: UUID | None = None,
        task_id: UUID | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[FakeEvent]:
        if self._fail_with:
            raise self._fail_with
        return self._events[:limit]


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def task_id() -> UUID:
    return uuid4()


@pytest.fixture
def config(tmp_path: Path) -> ClientConfig:
    return ClientConfig(
        api_base_url="https://example.com",
        machine_id=uuid4(),
        knowledge_vault_path=tmp_path / "vault",
        knowledge_graph_dir=tmp_path / "graph",
        knowledge_source_root=tmp_path / "src",
    )


@pytest.fixture
def api_client(project_id: UUID, task_id: UUID) -> FakeApiClient:
    return FakeApiClient(
        task=FakeTask(id=task_id, title="task", project_id=project_id),
        state=FakeProjectState(
            project_id=project_id,
            active_tasks=[{"id": str(task_id), "title": "task"}],
            active_claims=[{"id": str(uuid4()), "resource_path": "foo.py"}],
            generated_at=datetime.now(UTC),
        ),
        claims=[FakeClaim(id=uuid4(), project_id=project_id, resource_path="foo.py")],
        decisions=[FakeDecision(id=uuid4(), title="decision")],
        ai_work=[FakeAIWork(id=uuid4(), summary="summary")],
        events=[
            FakeEvent(
                event_id=uuid4(), event_type="ai_work.started", server_timestamp=datetime.now(UTC)
            )
        ],
    )


async def test_composer_includes_all_shared_sources(
    project_id: UUID, task_id: UUID, api_client: FakeApiClient, config: ClientConfig
) -> None:
    composer = ContextPackageComposer(api_client, config)
    package = await composer.generate(project_id, task_id=task_id)

    assert package.manifest.schema_version == 1
    assert package.manifest.project_id == project_id
    assert package.manifest.task_id == task_id
    kinds = {s.kind for s in package.manifest.sources}
    assert kinds >= {"task", "project_state", "claims", "decisions", "ai_work", "events"}
    assert not package.manifest.truncated


async def test_composer_omits_task_when_not_requested(
    project_id: UUID, api_client: FakeApiClient, config: ClientConfig
) -> None:
    composer = ContextPackageComposer(api_client, config)
    package = await composer.generate(project_id)

    kinds = {s.kind for s in package.manifest.sources}
    assert "task" not in kinds
    assert "project_state" in kinds


async def test_composer_includes_memory_when_configured(
    project_id: UUID,
    task_id: UUID,
    api_client: FakeApiClient,
    config: ClientConfig,
) -> None:
    vault = config.knowledge_vault_path
    assert vault is not None
    vault.mkdir(parents=True, exist_ok=True)
    exposed = vault / "projects" / "slug"
    exposed.mkdir(parents=True)
    (exposed / "note.md").write_text("# Note\nsearchable content", encoding="utf-8")

    memory = VaultMemoryProvider(
        vault_root=vault,
        scope=ScopePolicy(allowed_prefixes=("projects/slug/",)),
    )
    composer = ContextPackageComposer(api_client, config, memory_provider=memory)
    options = ContextPackageOptions(include_memory=True, memory_query="searchable", memory_limit=5)
    package = await composer.generate(project_id, task_id=task_id, options=options)

    memory_sources = [s for s in package.manifest.sources if s.kind == "memory"]
    assert memory_sources
    assert memory_sources[0].included == 1


async def test_composer_includes_graph_when_configured(
    project_id: UUID,
    task_id: UUID,
    api_client: FakeApiClient,
    config: ClientConfig,
) -> None:
    graph_dir = config.knowledge_graph_dir
    assert graph_dir is not None
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "label": "task",
                        "source_file": "tasks.py",
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    (graph_dir / "manifest.json").write_text(
        json.dumps({"tasks.py": {"mtime": 0}}), encoding="utf-8"
    )

    graph = GraphifyGraphProvider(graph_dir=graph_dir)
    composer = ContextPackageComposer(api_client, config, graph_provider=graph)
    options = ContextPackageOptions(include_graph=True, graph_query="task", graph_limit=5)
    package = await composer.generate(project_id, task_id=task_id, options=options)

    graph_sources = [s for s in package.manifest.sources if s.kind == "graph"]
    assert graph_sources
    assert graph_sources[0].included == 1


async def test_composer_omits_shared_sources_when_server_unreachable(
    project_id: UUID, config: ClientConfig
) -> None:
    failing_api = FakeApiClient(fail_with=TransportError("offline"))
    composer = ContextPackageComposer(failing_api, config)
    package = await composer.generate(project_id)

    assert not package.manifest.sources
    assert all(o.reason == "server_unreachable" for o in package.manifest.omitted)


async def test_composer_applies_hard_budget(
    project_id: UUID, task_id: UUID, api_client: FakeApiClient, config: ClientConfig
) -> None:
    # Force budget so low that only the highest-priority source can stay.
    options = ContextPackageOptions(budget_bytes=200)
    composer = ContextPackageComposer(api_client, config)
    package = await composer.generate(project_id, task_id=task_id, options=options)

    assert package.manifest.truncated
    # Some lower-priority source should have been dropped.
    dropped = {o.kind for o in package.manifest.omitted if o.reason == "budget"}
    assert dropped


async def test_composer_manifest_size_tracks_data(
    project_id: UUID, task_id: UUID, api_client: FakeApiClient, config: ClientConfig
) -> None:
    composer = ContextPackageComposer(api_client, config)
    package = await composer.generate(project_id, task_id=task_id)

    assert package.size_bytes() > 0
    assert _json_size(package.data) < package.size_bytes()
