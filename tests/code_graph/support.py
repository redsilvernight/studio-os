from __future__ import annotations

import asyncio
import hashlib
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from studio_code_graph.provider import (
    BuildRequest,
    CodeGraphBuildError,
    ProbeState,
    ProviderProbe,
    RepoGraph,
)
from studio_code_graph.service import CodeGraphService
from studio_contracts.local.common import LocalResourceKind, build_local_uri
from studio_contracts.local.graph import (
    Confidence,
    GraphEdge,
    GraphNode,
    GraphNodeRef,
    GraphProvenance,
    NodeKind,
    RelationKind,
)
from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import (
    CodeGraphConfig,
    LocalFeatures,
    LocalWorkspaceConfig,
    WorkspaceRoots,
)

WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")
PROFILE = ProfileRef(profile_id="default", server_origin="https://studio.example.test")
NOW = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
_DEF = re.compile(r"^(?:def|class)\s+([A-Za-z_]\w*)", re.MULTILINE)
_IMPORT = re.compile(r"^import\s+([A-Za-z_]\w*)", re.MULTILINE)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.test", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def init_repo(root: Path, files: dict[str, str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    for relative, content in (files or {}).items():
        write(root, relative, content)
    if files:
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init")
    return root


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit_all(root: Path, message: str = "change") -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def make_config(
    repos: dict[str, Path],
    *,
    workspace_id: UUID = WORKSPACE_ID,
    enabled: bool = True,
    provider_id: str = "fake",
    languages: list[str] | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    repo_names: list[str] | None = None,
    workspace_root: Path | None = None,
) -> LocalWorkspaceConfig:
    root = workspace_root or next(iter(repos.values())).parent
    return LocalWorkspaceConfig(
        workspace_id=workspace_id,
        profile=PROFILE,
        project_id=PROJECT_ID,
        roots=WorkspaceRoots(
            workspace_root=str(root),
            repo_roots=[{"name": name, "path": str(path)} for name, path in repos.items()],
        ),
        features=LocalFeatures(code_graph=enabled),
        code_graph=CodeGraphConfig(
            provider_id=provider_id,
            repo_names=repo_names if repo_names is not None else list(repos),
            languages=languages or [],
            include_globs=include or [],
            exclude_globs=exclude or [],
            index={"directory_name": "code"},
        )
        if enabled
        else None,
        created_at=NOW,
        updated_at=NOW,
    )


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:24]


@dataclass
class FakeProvider:
    """A second `CodeGraphProvider`, built only from the neutral contract: it
    indexes `def`/`class` and `import` lines of Python files."""

    provider_id: str = "fake"
    display_name: str = "Fake provider"
    capabilities: tuple[str, ...] = ("files", "symbols.function", "relations.contains")
    language_by_extension: dict[str, str] = field(default_factory=lambda: {".py": "python"})
    probe_result: ProviderProbe = field(
        default_factory=lambda: ProviderProbe(ProbeState.AVAILABLE, "1.2.3")
    )
    failure: CodeGraphBuildError | None = None
    crash: Exception | None = None
    gate: asyncio.Event | None = None
    delay: float = 0.0
    requests: list[BuildRequest] = field(default_factory=list)
    on_build: Callable[[BuildRequest], None] | None = None

    def probe(self) -> ProviderProbe:
        return self.probe_result

    async def build(self, request: BuildRequest, source_id: str) -> RepoGraph:
        self.requests.append(request)
        if self.on_build is not None:
            self.on_build(request)
        if self.gate is not None:
            await self.gate.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.crash is not None:
            raise self.crash
        if self.failure is not None:
            raise self.failure
        return self._index(request, source_id)

    def _provenance(self, source_id: str) -> GraphProvenance:
        return GraphProvenance(
            source_id=source_id, extractor="fake.ast", confidence=Confidence.EXTRACTED
        )

    def _node(
        self, request: BuildRequest, source_id: str, kind: NodeKind, label: str, path: str
    ) -> GraphNode:
        return GraphNode(
            node_id="n-" + _digest(request.repo_name, kind.value, path, label),
            kind=kind,
            label=label,
            uri=build_local_uri(
                LocalResourceKind.CODE, request.workspace_id, f"{request.repo_name}/{path}"
            ),
            provenance=self._provenance(source_id),
            metadata={"repo": request.repo_name, "path": path},
        )

    def _edge(
        self, source_id: str, kind: RelationKind, source: GraphNode, target: GraphNode
    ) -> GraphEdge:
        return GraphEdge(
            edge_id="e-" + _digest(kind.value, source.node_id, target.node_id),
            kind=kind,
            source=GraphNodeRef(source_id=source_id, node_id=source.node_id),
            target=GraphNodeRef(source_id=source_id, node_id=target.node_id),
            provenance=self._provenance(source_id),
        )

    def _index(self, request: BuildRequest, source_id: str) -> RepoGraph:
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        files: dict[str, GraphNode] = {}
        sources: dict[str, str] = {}
        for path in sorted(request.repo_root.rglob("*.py")):
            relative = path.relative_to(request.repo_root).as_posix()
            if relative.startswith(".git/"):
                continue
            file_node = self._node(request, source_id, NodeKind.FILE, relative, relative)
            files[Path(relative).stem] = file_node
            nodes[file_node.node_id] = file_node
            sources[relative] = path.read_text(encoding="utf-8")
            for name in _DEF.findall(sources[relative]):
                symbol = self._node(request, source_id, NodeKind.FUNCTION, name, relative)
                nodes[symbol.node_id] = symbol
                edges.append(self._edge(source_id, RelationKind.CONTAINS, file_node, symbol))
        for relative, text in sources.items():
            origin = files[Path(relative).stem]
            for module in _IMPORT.findall(text):
                target = files.get(module)
                if target is not None and target.node_id != origin.node_id:
                    edges.append(self._edge(source_id, RelationKind.IMPORTS, origin, target))
        return RepoGraph(
            repo_name=request.repo_name,
            provider_id=self.provider_id,
            provider_version=self.probe_result.version,
            nodes=list(nodes.values()),
            edges=edges,
            languages=("python",) if nodes else (),
        )


def make_service(
    tmp_path: Path, provider: FakeProvider | None = None, **options: object
) -> tuple[CodeGraphService, FakeProvider]:
    chosen = provider or FakeProvider()
    settings: dict[str, object] = {
        "debounce_seconds": 0.0,
        "freshness_ttl_seconds": 0.0,
        "probe_ttl_seconds": 0.0,
        **options,
    }
    service = CodeGraphService([chosen], tmp_path / "cache", **settings)  # type: ignore[arg-type]
    return service, chosen


APP_FILES = {
    "src/main.py": "import util\n\ndef main():\n    return util.helper()\n",
    "src/util.py": "class Greeter:\n    pass\n\ndef helper():\n    return 1\n",
}
