from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import StringConstraints, TypeAdapter, ValidationError
from studio_contracts.local.common import (
    MAX_PAGE_LIMIT,
    BoundedMetadata,
    ComponentId,
    ComponentState,
    LocalError,
    LocalErrorCode,
    LocalResourceKind,
    LocalResourceUri,
    SafeText,
    ShortText,
    build_local_uri,
    parse_local_uri,
)
from studio_contracts.local.graph import (
    Confidence,
    GraphCounts,
    GraphDirection,
    GraphEdge,
    GraphExpandRequest,
    GraphNode,
    GraphNodeRef,
    GraphPage,
    GraphPageRequest,
    GraphProvenance,
    GraphSource,
    GraphSourceKind,
    NodeKind,
)
from studio_contracts.local.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentRef,
    KnowledgeGetDocumentRequest,
    KnowledgeIntegration,
    KnowledgeReindexMode,
    KnowledgeReindexRequest,
    KnowledgeReindexResult,
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeStatus,
)
from studio_contracts.local.provider import (
    INDEX_STATE_COMPONENT,
    IndexInfo,
    IndexState,
    ProviderInfo,
)

from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.index import (
    MAX_SNIPPET_CHARS,
    GraphEdgeRow,
    GraphNodeRow,
    IndexedDocument,
    IndexedHit,
    IndexSnapshot,
    KnowledgeIndex,
)
from studio_client.knowledge.memory import (
    DEFAULT_EXCERPT_CHARS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_READ_CHARS,
    MemoryNoteHit,
    MemoryProposal,
    MemoryReadResult,
    MemorySearchResult,
)
from studio_client.knowledge.obsidian import (
    OBSIDIAN_INTEGRATION_ID,
    ObsidianProbe,
    detect_obsidian,
)
from studio_client.knowledge.scope import ScopePolicy
from studio_client.knowledge.vault import (
    DEFAULT_EXCLUDE_GLOBS,
    DEFAULT_INCLUDE_GLOBS,
    VaultState,
    vault_state,
)

KNOWLEDGE_PROVIDER_ID = "markdown-files"
KNOWLEDGE_DISPLAY_NAME = "Markdown files"
KNOWLEDGE_PROVIDER_VERSION = "1.0.0"
KNOWLEDGE_CAPABILITIES = ["knowledge.graph", "knowledge.index", "knowledge.read"]
MAX_INTEGRATIONS = 8
MAX_OUTGOING_LINKS = 200
MAX_DOCUMENT_BYTES = 262_144

_SNIPPET_TEXT = Annotated[SafeText, StringConstraints(max_length=MAX_SNIPPET_CHARS)]
_SHORT_ADAPTER = TypeAdapter(ShortText)
_SNIPPET_ADAPTER = TypeAdapter(_SNIPPET_TEXT)
_SAFE_ADAPTER = TypeAdapter(SafeText)
_URI_ADAPTER = TypeAdapter(LocalResourceUri)
_LABEL_FALLBACK = "untitled"


def _is_safe(text: str) -> bool:
    try:
        _SAFE_ADAPTER.validate_python(text)
    except ValidationError:
        return False
    return True


def safe_short_text(candidate: str, fallback: str = _LABEL_FALLBACK) -> str:
    """A `ShortText`-safe label: credential-shaped or path-shaped content never
    reaches a contract model, and the fallback is always valid."""
    text = " ".join(candidate.split())[:200]
    try:
        return _SHORT_ADAPTER.validate_python(text)
    except ValidationError:
        pass
    kept = " ".join(word for word in text.split() if _is_safe(word))[:200]
    try:
        return _SHORT_ADAPTER.validate_python(kept)
    except ValidationError:
        return fallback


def safe_snippet(candidate: str) -> str:
    text = " ".join(candidate.split())[:MAX_SNIPPET_CHARS]
    try:
        return _SNIPPET_ADAPTER.validate_python(text)
    except ValidationError:
        return ""


@dataclass(frozen=True)
class IntegrationProbe:
    integration_id: str
    state: ComponentState


def disabled_knowledge_status(workspace_id: UUID) -> KnowledgeStatus:
    """The explicit status of a workspace whose knowledge feature is off: no
    provider, no index, no service — never a silent empty vault."""
    return KnowledgeStatus(
        workspace_id=workspace_id,
        state=ComponentState.DISABLED,
        provider=None,
        index=None,
        error=LocalError(
            code=LocalErrorCode.FEATURE_DISABLED,
            message="Knowledge is disabled for this workspace.",
            component=ComponentId.KNOWLEDGE,
            retryable=False,
        ),
    )


class VaultKnowledgeProvider:
    """P1 `KnowledgeProvider` over a local Markdown vault.

    Markdown is canonical; the index and the graph are derived and rebuildable.
    Every method is local and side-effect free apart from `reindex`, which only
    rewrites the derived index. Nothing is ever uploaded, published or sent to
    the server."""

    def __init__(
        self,
        *,
        workspace_id: UUID,
        vault_root: Path,
        index: KnowledgeIndex,
        provider_id: str = KNOWLEDGE_PROVIDER_ID,
        provider_version: str = KNOWLEDGE_PROVIDER_VERSION,
        scope: ScopePolicy | None = None,
        integrations: Sequence[IntegrationProbe] | None = None,
        obsidian: ObsidianProbe | None = None,
        source_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
        include_globs: Sequence[str] = DEFAULT_INCLUDE_GLOBS,
        exclude_globs: Sequence[str] = DEFAULT_EXCLUDE_GLOBS,
    ) -> None:
        self._workspace_id = workspace_id
        self._vault_root = vault_root
        self._index = index
        self._provider_id = provider_id
        self._provider_version = provider_version
        self._scope = scope
        self._integrations = tuple(integrations) if integrations is not None else None
        self._obsidian = obsidian
        self._source_id = source_id or f"knowledge-{provider_id}"
        self._clock = clock or (lambda: datetime.now(UTC))
        self._include_globs = tuple(include_globs)
        self._exclude_globs = tuple(exclude_globs)

    @property
    def index(self) -> KnowledgeIndex:
        return self._index

    @property
    def vault_root(self) -> Path:
        return self._vault_root

    @property
    def workspace_id(self) -> UUID:
        return self._workspace_id

    @property
    def source_id(self) -> str:
        return self._source_id

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider_id=self._provider_id,
            display_name=KNOWLEDGE_DISPLAY_NAME,
            provider_version=self._provider_version,
            capabilities=list(KNOWLEDGE_CAPABILITIES),
        )

    def _exposed(self, relative_path: str) -> bool:
        if self._scope is None:
            return True
        return self._scope.is_exposed(relative_path)

    def _vault_problem(self) -> LocalError | None:
        state = vault_state(self._vault_root)
        if state in (VaultState.MISSING, VaultState.NOT_A_DIRECTORY, VaultState.INACCESSIBLE):
            return LocalError(
                code=LocalErrorCode.WORKSPACE_INACCESSIBLE,
                message="The vault folder is missing or cannot be read.",
                component=ComponentId.KNOWLEDGE,
                retryable=False,
                details={"reason": state.value},
            )
        return None

    def _integrations_list(self) -> list[KnowledgeIntegration]:
        if self._integrations is None:
            probe = self._obsidian or detect_obsidian()
            self._obsidian = probe
            entries = [(OBSIDIAN_INTEGRATION_ID, probe.state)]
        else:
            entries = [(item.integration_id, item.state) for item in self._integrations]
        return [
            KnowledgeIntegration(integration_id=identifier, state=state)
            for identifier, state in entries[:MAX_INTEGRATIONS]
        ]

    @staticmethod
    def _index_info(snapshot: IndexSnapshot) -> IndexInfo:
        if snapshot.state is IndexState.ABSENT:
            return IndexInfo(state=IndexState.ABSENT)
        if snapshot.state is IndexState.INDEXING:
            return IndexInfo(state=IndexState.INDEXING, progress_percent=snapshot.progress_percent)
        if snapshot.state is IndexState.CORRUPT:
            return IndexInfo(state=IndexState.CORRUPT)
        return IndexInfo(
            state=snapshot.state,
            built_at=snapshot.built_at,
            source_fingerprint=snapshot.source_fingerprint,
            item_count=snapshot.item_count,
        )

    @staticmethod
    def _index_error(state: IndexState) -> LocalError | None:
        if state is IndexState.CORRUPT:
            return LocalError(
                code=LocalErrorCode.INDEX_CORRUPT,
                message="The knowledge index is corrupt and must be rebuilt.",
                component=ComponentId.KNOWLEDGE,
                retryable=False,
            )
        if state is IndexState.ABSENT:
            return LocalError(
                code=LocalErrorCode.INDEX_ABSENT,
                message="The knowledge index has not been built yet.",
                component=ComponentId.KNOWLEDGE,
                retryable=False,
            )
        return None

    def status(self) -> KnowledgeStatus:
        problem = self._vault_problem()
        if problem is not None:
            return KnowledgeStatus(
                workspace_id=self._workspace_id,
                state=ComponentState.UNAVAILABLE,
                provider=self.provider_info(),
                index=IndexInfo(state=IndexState.ABSENT),
                integrations=self._integrations_list(),
                error=problem,
            )
        snapshot = self._index.snapshot(self._vault_root)
        return KnowledgeStatus(
            workspace_id=self._workspace_id,
            state=INDEX_STATE_COMPONENT[snapshot.state],
            provider=self.provider_info(),
            index=self._index_info(snapshot),
            integrations=self._integrations_list(),
            error=self._index_error(snapshot.state),
        )

    def _require_workspace(self, workspace_id: UUID) -> None:
        if workspace_id != self._workspace_id:
            raise KnowledgeError(KnowledgeError.OUT_OF_SCOPE, "the request names another workspace")

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        self._require_workspace(request.workspace_id)
        if self._vault_problem() is not None:
            return KnowledgeSearchResult(
                hits=[], index_state=ComponentState.UNAVAILABLE, complete=False
            )
        snapshot = self._index.snapshot(self._vault_root)
        component_state = INDEX_STATE_COMPONENT[snapshot.state]
        if snapshot.state not in (IndexState.READY, IndexState.STALE):
            return KnowledgeSearchResult(hits=[], index_state=component_state, complete=False)
        rows, next_cursor = self._index.search(
            request.query, limit=request.limit, cursor=request.cursor
        )
        hits = [self._hit(row) for row in rows if self._exposed(row.relative_path)]
        return KnowledgeSearchResult(
            hits=hits[: request.limit],
            next_cursor=next_cursor,
            index_state=component_state,
            complete=component_state is ComponentState.READY and next_cursor is None,
        )

    def _hit(self, row: IndexedHit) -> KnowledgeSearchHit:
        return KnowledgeSearchHit(
            document=self._document_ref(row.uri, row.title, row.content_hash, row.modified_at),
            score=row.score,
            snippet=safe_snippet(row.snippet),
        )

    def _document_ref(
        self, uri: str, title: str, content_hash: str, modified_at: datetime
    ) -> KnowledgeDocumentRef:
        return KnowledgeDocumentRef(
            uri=uri,
            title=safe_short_text(title),
            content_hash=content_hash,
            modified_at=modified_at,
        )

    def get_document(self, request: KnowledgeGetDocumentRequest) -> KnowledgeDocument:
        kind, workspace_id, relative_path, _ = parse_local_uri(request.uri)
        if kind is not LocalResourceKind.KNOWLEDGE:
            raise KnowledgeError(KnowledgeError.NOT_FOUND, "not a knowledge document")
        self._require_workspace(workspace_id)
        if not relative_path or not self._exposed(relative_path):
            raise KnowledgeError(KnowledgeError.OUT_OF_SCOPE, "the document is outside the scope")
        row = self._index.document(relative_path)
        if row is None:
            raise KnowledgeError(KnowledgeError.NOT_FOUND, "the document is not indexed")
        markdown = self._read(row)
        return KnowledgeDocument(
            document=self._document_ref(row.uri, row.title, row.content_hash, row.modified_at),
            markdown=markdown[: request.max_bytes],
            truncated=len(markdown) > request.max_bytes,
            outgoing_links=[
                GraphNodeRef(source_id=self._source_id, node_id=node_id)
                for _, node_id in row.outgoing[:MAX_OUTGOING_LINKS]
            ],
        )

    def _read(self, row: IndexedDocument) -> str:
        try:
            return (self._vault_root / row.relative_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise KnowledgeError(KnowledgeError.NOT_FOUND, "the document is unreadable") from exc

    def reindex(self, request: KnowledgeReindexRequest) -> KnowledgeReindexResult:
        self._require_workspace(request.workspace_id)
        problem = self._vault_problem()
        if problem is not None:
            return KnowledgeReindexResult(
                accepted=False, operation_id=None, state=ComponentState.UNAVAILABLE, error=problem
            )
        full = request.mode is KnowledgeReindexMode.FULL_REBUILD
        try:
            snapshot = self._index.rebuild(self._vault_root, full=full)
        except (KnowledgeError, sqlite3.Error, OSError) as exc:
            reason = exc.reason if isinstance(exc, KnowledgeError) else "index_unwritable"
            return KnowledgeReindexResult(
                accepted=False,
                operation_id=None,
                state=ComponentState.ERROR,
                error=LocalError(
                    code=LocalErrorCode.INDEX_CORRUPT,
                    message="The knowledge index could not be rebuilt.",
                    component=ComponentId.KNOWLEDGE,
                    retryable=True,
                    details={"reason": reason},
                ),
            )
        return KnowledgeReindexResult(
            accepted=True,
            operation_id=str(uuid4()),
            state=INDEX_STATE_COMPONENT[snapshot.state],
        )

    def graph_page(self, request: GraphPageRequest) -> GraphPage:
        self._require_workspace(request.workspace_id)
        snapshot = self._index.snapshot(self._vault_root)
        source = self._source(snapshot.source_fingerprint)
        if snapshot.state not in (IndexState.READY, IndexState.STALE):
            return self._empty_page(source)
        snapshot_graph = self._index.graph()
        nodes = list(snapshot_graph.nodes)
        if request.node_kinds:
            allowed = set(request.node_kinds)
            nodes = [node for node in nodes if node.kind in allowed]
        return self._page(
            source,
            nodes,
            list(snapshot_graph.edges),
            offset=_cursor_offset(request.cursor, "n:"),
            limit=request.limit,
        )

    def graph_expand(self, request: GraphExpandRequest) -> GraphPage:
        self._require_workspace(request.workspace_id)
        if request.node.source_id != self._source_id:
            raise KnowledgeError(KnowledgeError.NOT_FOUND, "the node belongs to another source")
        snapshot = self._index.snapshot(self._vault_root)
        source = self._source(snapshot.source_fingerprint)
        if snapshot.state not in (IndexState.READY, IndexState.STALE):
            return self._empty_page(source)
        snapshot_graph = self._index.graph()
        by_id = {node.node_id: node for node in snapshot_graph.nodes}
        if request.node.node_id not in by_id:
            raise KnowledgeError(KnowledgeError.NOT_FOUND, "the node is not in the index")
        relations = set(request.relations)
        incident = [
            edge
            for edge in snapshot_graph.edges
            if _incident(edge, request.node.node_id, request.direction)
            and (not relations or edge.kind in relations)
        ]
        neighbours: list[str] = []
        for edge in incident:
            other = (
                edge.target_node_id
                if edge.source_node_id == request.node.node_id
                else edge.source_node_id
            )
            if other != request.node.node_id and other in by_id and other not in neighbours:
                neighbours.append(other)
        neighbours.sort()
        offset = _cursor_offset(request.cursor, "n:")
        window = neighbours[offset : offset + max(request.limit - 1, 0)]
        truncated = offset + len(window) < len(neighbours)
        included = sorted({request.node.node_id, *window})
        page_nodes = [by_id[node_id] for node_id in included]
        return self._page(
            source,
            page_nodes,
            incident,
            offset=0,
            limit=len(page_nodes),
            truncated=truncated,
            next_cursor=f"n:{offset + len(window)}" if truncated else None,
        )

    def _empty_page(self, source: GraphSource) -> GraphPage:
        return GraphPage(source=source, counts=GraphCounts(nodes=0, edges=0, total_nodes=0))

    def _source(self, fingerprint: str | None) -> GraphSource:
        return GraphSource(
            source_id=self._source_id,
            kind=GraphSourceKind.KNOWLEDGE,
            provider_id=self._provider_id,
            workspace_id=self._workspace_id,
            generated_at=self._clock(),
            index_fingerprint=fingerprint,
        )

    def _page(
        self,
        source: GraphSource,
        nodes: Sequence[GraphNodeRow],
        edges: Sequence[GraphEdgeRow],
        *,
        offset: int,
        limit: int,
        truncated: bool | None = None,
        next_cursor: str | None = None,
    ) -> GraphPage:
        page_rows = list(nodes[offset : offset + limit])
        page_ids = {row.node_id for row in page_rows}
        candidates = [
            edge
            for edge in edges
            if edge.source_node_id in page_ids or edge.target_node_id in page_ids
        ]
        missing = sorted(
            {
                endpoint
                for edge in candidates
                for endpoint in (edge.source_node_id, edge.target_node_id)
                if endpoint not in page_ids
            }
        )
        frontier_ids = set(missing[:MAX_PAGE_LIMIT])
        reachable = page_ids | frontier_ids
        kept = [
            edge
            for edge in candidates
            if edge.source_node_id in reachable and edge.target_node_id in reachable
        ]
        is_truncated = truncated if truncated is not None else offset + len(page_rows) < len(nodes)
        cursor = next_cursor
        if cursor is None and is_truncated:
            cursor = f"n:{offset + len(page_rows)}"
        return GraphPage(
            source=source,
            nodes=[self._node(source, row) for row in page_rows],
            edges=[self._edge(source, row) for row in kept],
            frontier=[
                GraphNodeRef(source_id=self._source_id, node_id=node_id)
                for node_id in sorted(frontier_ids)
            ],
            next_cursor=cursor,
            truncated=is_truncated,
            counts=GraphCounts(
                nodes=len(page_rows),
                edges=len(kept),
                total_nodes=len(nodes),
                total_edges=len(edges),
            ),
        )

    def _node(self, source: GraphSource, row: GraphNodeRow) -> GraphNode:
        return GraphNode(
            node_id=row.node_id,
            kind=row.kind,
            label=safe_short_text(row.label),
            uri=_safe_uri(row.uri),
            provenance=self._provenance(source, row.extractor, row.evidence_uri),
            metadata=_metadata(row),
        )

    def _edge(self, source: GraphSource, row: GraphEdgeRow) -> GraphEdge:
        return GraphEdge(
            edge_id=row.edge_id,
            kind=row.kind,
            source=GraphNodeRef(source_id=self._source_id, node_id=row.source_node_id),
            target=GraphNodeRef(source_id=self._source_id, node_id=row.target_node_id),
            provenance=self._provenance(source, row.extractor, row.evidence_uri),
        )

    def _provenance(
        self, source: GraphSource, extractor: str, evidence_uri: str | None
    ) -> GraphProvenance:
        return GraphProvenance(
            source_id=source.source_id,
            extractor=extractor,
            confidence=Confidence.EXTRACTED,
            evidence=_safe_uri(evidence_uri),
        )


class KnowledgeMemoryProvider:
    """`MemoryProvider`-shaped adapter over the indexed vault, so the existing
    local MCP memory tools and the Context Package can consume the index
    without any change to their own contract."""

    def __init__(
        self,
        provider: VaultKnowledgeProvider,
        *,
        scope: ScopePolicy | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
    ) -> None:
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        if excerpt_chars <= 0:
            raise ValueError("excerpt_chars must be positive")
        self._provider = provider
        self._scope = scope or ScopePolicy()
        self._max_results = max_results
        self._excerpt_chars = excerpt_chars

    def search(self, query: str, *, max_results: int | None = None) -> MemorySearchResult:
        limit = max_results if max_results is not None else self._max_results
        if limit <= 0:
            raise ValueError("max_results must be positive")
        needle = query.strip()
        if not needle:
            return MemorySearchResult(matches=[])
        try:
            result = self._provider.search(
                KnowledgeSearchRequest(
                    workspace_id=self._provider.workspace_id,
                    query=needle[:200],
                    limit=min(limit, 100),
                )
            )
        except KnowledgeError as exc:
            return MemorySearchResult(matches=[], reason=exc.reason)
        matches: list[MemoryNoteHit] = []
        for hit in result.hits:
            relative = parse_local_uri(hit.document.uri)[2]
            if not self._scope.is_exposed(relative):
                continue
            excerpt, truncated = _excerpt(hit.snippet, self._excerpt_chars)
            matches.append(
                MemoryNoteHit(
                    path=relative,
                    title=hit.document.title,
                    excerpt=excerpt,
                    truncated=truncated,
                )
            )
        reason = None if result.index_state is ComponentState.READY else result.index_state.value
        return MemorySearchResult(matches=matches, reason=reason)

    def read(self, path: str, *, max_chars: int = DEFAULT_READ_CHARS) -> MemoryReadResult:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        resolved = self._scope.resolve(self._provider.vault_root, path)
        relative = resolved.relative_to(self._provider.vault_root.resolve()).as_posix()
        document = self._provider.get_document(
            KnowledgeGetDocumentRequest(
                uri=build_local_uri(
                    LocalResourceKind.KNOWLEDGE, self._provider.workspace_id, relative
                ),
                max_bytes=min(max_chars, MAX_DOCUMENT_BYTES),
            )
        )
        return MemoryReadResult(
            path=relative,
            title=document.document.title,
            content=document.markdown,
            truncated=document.truncated,
        )

    def propose(self, proposal: MemoryProposal) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "the vault index is read-only; memory writes need the server approval loop",
        )

    def write_if_authorized(self, proposal: MemoryProposal) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "the vault index is read-only; memory writes need the server approval loop",
        )

    def append_task_log(self, entry: dict[str, object]) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "the vault index is read-only; memory writes need the server approval loop",
        )

    def create_decision_note(self, note: dict[str, object]) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "the vault index is read-only; memory writes need the server approval loop",
        )


def _excerpt(snippet: str, max_chars: int) -> tuple[str, bool]:
    if len(snippet) <= max_chars:
        return snippet, False
    return snippet[:max_chars], True


def _safe_uri(candidate: str | None) -> LocalResourceUri | None:
    if not candidate:
        return None
    try:
        return _URI_ADAPTER.validate_python(candidate)
    except ValidationError:
        return None


def _metadata(row: GraphNodeRow) -> BoundedMetadata:
    if row.kind is not NodeKind.DOCUMENT or row.uri is None:
        return {}
    relative = parse_local_uri(row.uri)[2]
    if not relative or not _is_safe(relative):
        return {}
    return {"path": relative}


def _incident(edge: GraphEdgeRow, node_id: str, direction: GraphDirection) -> bool:
    if direction is GraphDirection.OUT:
        return edge.source_node_id == node_id
    if direction is GraphDirection.IN:
        return edge.target_node_id == node_id
    return node_id in (edge.source_node_id, edge.target_node_id)


def _cursor_offset(cursor: str | None, prefix: str) -> int:
    if not cursor or not cursor.startswith(prefix):
        return 0
    try:
        return max(0, int(cursor[len(prefix) :]))
    except ValueError:
        return 0
