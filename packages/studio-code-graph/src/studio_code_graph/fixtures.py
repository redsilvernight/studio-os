from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from studio_contracts.local.code_graph import CodeGraphStatus, CodeSymbolResult
from studio_contracts.local.common import (
    ComponentState,
    LocalErrorCode,
    LocalResourceKind,
    build_local_uri,
)
from studio_contracts.local.graph import (
    Confidence,
    GraphEdge,
    GraphNode,
    GraphNodeRef,
    GraphPage,
    GraphProvenance,
    GraphSource,
    GraphSourceKind,
    NodeKind,
    RelationKind,
)
from studio_contracts.local.provider import IndexInfo, IndexState, ProviderInfo

from studio_code_graph.errors import make_error
from studio_code_graph.index import CodeGraphIndex

FIXTURE_WORKSPACE_ID = UUID("00000000-0000-4000-8000-00000000c0de")
FIXTURE_SOURCE_ID = "code.fixture"
FIXTURE_PROVIDER_ID = "fixture"
FIXTURE_REPO = "app"
FIXTURE_BUILT_AT = datetime(2026, 1, 1, tzinfo=UTC)
FIXTURE_CAPABILITIES = (
    "code.files",
    "code.types",
    "code.functions",
    "code.imports",
    "code.calls",
    "code.contains",
)

FIXTURE_NAMES = (
    "empty",
    "small",
    "files",
    "functions",
    "imports",
    "calls",
    "contains",
    "partial",
    "stale",
    "indexing",
    "provider_absent",
    "error",
    "corrupt",
)


@dataclass(frozen=True)
class CodeGraphFixture:
    name: str
    status: CodeGraphStatus
    page: GraphPage | None
    symbols: CodeSymbolResult


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:24]


def _provenance(confidence: Confidence = Confidence.EXTRACTED) -> GraphProvenance:
    evidence = None
    if confidence is Confidence.INFERRED:
        evidence = build_local_uri(
            LocalResourceKind.CODE, FIXTURE_WORKSPACE_ID, f"{FIXTURE_REPO}/src/main.py"
        )
    return GraphProvenance(
        source_id=FIXTURE_SOURCE_ID,
        extractor=f"{FIXTURE_PROVIDER_ID}.ast",
        confidence=confidence,
        evidence=evidence,
    )


def _node(kind: NodeKind, label: str, path: str, line: int | None = None) -> GraphNode:
    return GraphNode(
        node_id="n-" + _digest(kind.value, path, label),
        kind=kind,
        label=label,
        uri=build_local_uri(
            LocalResourceKind.CODE,
            FIXTURE_WORKSPACE_ID,
            f"{FIXTURE_REPO}/{path}",
            fragment=f"L{line}" if line else None,
        ),
        provenance=_provenance(),
        metadata={"repo": FIXTURE_REPO, "path": path, "language": "python"},
    )


def _edge(
    kind: RelationKind,
    source: GraphNode,
    target: GraphNode,
    confidence: Confidence = Confidence.EXTRACTED,
) -> GraphEdge:
    return GraphEdge(
        edge_id="e-" + _digest(kind.value, source.node_id, target.node_id),
        kind=kind,
        source=GraphNodeRef(source_id=FIXTURE_SOURCE_ID, node_id=source.node_id),
        target=GraphNodeRef(source_id=FIXTURE_SOURCE_ID, node_id=target.node_id),
        provenance=_provenance(confidence),
    )


@dataclass(frozen=True)
class _Repo:
    files: list[GraphNode]
    classes: list[GraphNode]
    functions: list[GraphNode]
    contains: list[GraphEdge]
    imports: list[GraphEdge]
    calls: list[GraphEdge]

    @property
    def nodes(self) -> list[GraphNode]:
        return [*self.files, *self.classes, *self.functions]


def _small_repo() -> _Repo:
    main = _node(NodeKind.FILE, "src/main.py", "src/main.py")
    util = _node(NodeKind.FILE, "src/util.py", "src/util.py")
    greeter = _node(NodeKind.CLASS, "Greeter", "src/util.py", 3)
    greet = _node(NodeKind.FUNCTION, "Greeter.greet", "src/util.py", 5)
    helper = _node(NodeKind.FUNCTION, "helper", "src/util.py", 9)
    entry = _node(NodeKind.FUNCTION, "main", "src/main.py", 4)
    return _Repo(
        files=[main, util],
        classes=[greeter],
        functions=[greet, helper, entry],
        contains=[
            _edge(RelationKind.CONTAINS, util, greeter),
            _edge(RelationKind.CONTAINS, greeter, greet),
            _edge(RelationKind.CONTAINS, util, helper),
            _edge(RelationKind.CONTAINS, main, entry),
        ],
        imports=[_edge(RelationKind.IMPORTS, main, util)],
        calls=[
            _edge(RelationKind.CALLS, entry, greet),
            _edge(RelationKind.CALLS, entry, helper, Confidence.INFERRED),
        ],
    )


def _index(nodes: list[GraphNode], edges: list[GraphEdge]) -> CodeGraphIndex:
    return CodeGraphIndex(FIXTURE_SOURCE_ID, hashlib.sha256(b"fixture").hexdigest(), nodes, edges)


def _source(fingerprint: str | None) -> GraphSource:
    return GraphSource(
        source_id=FIXTURE_SOURCE_ID,
        kind=GraphSourceKind.CODE,
        provider_id=FIXTURE_PROVIDER_ID,
        workspace_id=FIXTURE_WORKSPACE_ID,
        generated_at=FIXTURE_BUILT_AT,
        index_fingerprint=fingerprint,
    )


def _provider() -> ProviderInfo:
    return ProviderInfo(
        provider_id=FIXTURE_PROVIDER_ID,
        display_name="Fixture provider",
        provider_version="1.0.0",
        capabilities=list(FIXTURE_CAPABILITIES),
    )


def _symbols(index: CodeGraphIndex | None, state: IndexState) -> CodeSymbolResult:
    if index is None:
        return CodeSymbolResult(index_state=state, complete=False)
    refs, cursor = index.search("", [], 20, None)
    return CodeSymbolResult(
        symbols=refs, next_cursor=cursor, index_state=state, complete=state is IndexState.READY
    )


def _ready(
    name: str,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    *,
    stale: bool = False,
    page_limit: int = 100,
) -> CodeGraphFixture:
    index = _index(nodes, edges)
    fingerprint = hashlib.sha256(b"fixture").hexdigest()
    state = IndexState.STALE if stale else IndexState.READY
    status = CodeGraphStatus(
        workspace_id=FIXTURE_WORKSPACE_ID,
        state=ComponentState.STALE if stale else ComponentState.READY,
        provider=_provider(),
        index=IndexInfo(
            state=state,
            built_at=FIXTURE_BUILT_AT,
            source_fingerprint=fingerprint,
            item_count=len(nodes),
        ),
        languages=["python"] if nodes else [],
    )
    page = index.page(_source(fingerprint), page_limit, None, [])
    symbols = _symbols(index, state)
    return CodeGraphFixture(name, status, page, symbols)


def _without_page(name: str, status: CodeGraphStatus, state: IndexState) -> CodeGraphFixture:
    return CodeGraphFixture(name, status, None, _symbols(None, state))


def _indexing() -> CodeGraphFixture:
    status = CodeGraphStatus(
        workspace_id=FIXTURE_WORKSPACE_ID,
        state=ComponentState.INDEXING,
        provider=_provider(),
        index=IndexInfo(state=IndexState.INDEXING, item_count=0, progress_percent=40),
    )
    return _without_page("indexing", status, IndexState.INDEXING)


def _provider_absent() -> CodeGraphFixture:
    status = CodeGraphStatus(
        workspace_id=FIXTURE_WORKSPACE_ID,
        state=ComponentState.NOT_INSTALLED,
        error=make_error(
            LocalErrorCode.PROVIDER_NOT_INSTALLED, "code graph provider is not installed"
        ),
    )
    return _without_page("provider_absent", status, IndexState.ABSENT)


def _error() -> CodeGraphFixture:
    status = CodeGraphStatus(
        workspace_id=FIXTURE_WORKSPACE_ID,
        state=ComponentState.ERROR,
        provider=_provider(),
        error=make_error(
            LocalErrorCode.INTERNAL_ERROR,
            "code graph provider failed: process_failed",
            retryable=True,
        ),
    )
    return _without_page("error", status, IndexState.ABSENT)


def _corrupt() -> CodeGraphFixture:
    status = CodeGraphStatus(
        workspace_id=FIXTURE_WORKSPACE_ID,
        state=ComponentState.ERROR,
        provider=_provider(),
        index=IndexInfo(state=IndexState.CORRUPT),
        error=make_error(
            LocalErrorCode.INDEX_CORRUPT,
            "the stored code index is unreadable and will be rebuilt",
            retryable=True,
        ),
    )
    return _without_page("corrupt", status, IndexState.CORRUPT)


def build_fixture(name: str) -> CodeGraphFixture:
    repo = _small_repo()
    if name == "empty":
        return _ready(name, [], [])
    if name == "small":
        return _ready(name, repo.nodes, [*repo.contains, *repo.imports, *repo.calls])
    if name == "files":
        return _ready(name, repo.files, [])
    if name == "functions":
        return _ready(name, repo.nodes, repo.contains)
    if name == "imports":
        return _ready(name, repo.files, repo.imports)
    if name == "calls":
        return _ready(name, repo.functions, repo.calls)
    if name == "contains":
        return _ready(name, repo.nodes, repo.contains)
    if name == "partial":
        return _ready(name, repo.nodes, [*repo.contains, *repo.imports, *repo.calls], page_limit=2)
    if name == "stale":
        return _ready(name, repo.nodes, [*repo.contains, *repo.imports], stale=True)
    if name == "indexing":
        return _indexing()
    if name == "provider_absent":
        return _provider_absent()
    if name == "error":
        return _error()
    if name == "corrupt":
        return _corrupt()
    raise KeyError(name)


def all_fixtures() -> dict[str, CodeGraphFixture]:
    return {name: build_fixture(name) for name in FIXTURE_NAMES}
