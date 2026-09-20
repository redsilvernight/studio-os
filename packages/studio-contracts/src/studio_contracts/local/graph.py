from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.local.common import (
    MAX_PAGE_LIMIT,
    BoundedMetadata,
    Identifier,
    LocalContractModel,
    LocalResourceUri,
    OpaqueId,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)


class GraphSourceKind(StrEnum):
    KNOWLEDGE = "knowledge"
    CODE = "code"
    PROJECTION = "projection"


class NodeKind(StrEnum):
    DOCUMENT = "document"
    HEADING = "heading"
    TAG = "tag"
    FILE = "file"
    PACKAGE = "package"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"


class RelationKind(StrEnum):
    LINKS_TO = "links_to"
    TAGGED_WITH = "tagged_with"
    EMBEDS = "embeds"
    CONTAINS = "contains"
    IMPORTS = "imports"
    CALLS = "calls"
    DEFINES = "defines"
    INHERITS = "inherits"
    REFERENCES = "references"
    DOCUMENTS = "documents"


KNOWLEDGE_NODE_KINDS = frozenset({NodeKind.DOCUMENT, NodeKind.HEADING, NodeKind.TAG})
CODE_NODE_KINDS = frozenset(
    {NodeKind.FILE, NodeKind.PACKAGE, NodeKind.MODULE, NodeKind.CLASS, NodeKind.FUNCTION}
)
KNOWLEDGE_RELATIONS = frozenset(
    {
        RelationKind.LINKS_TO,
        RelationKind.TAGGED_WITH,
        RelationKind.EMBEDS,
        RelationKind.CONTAINS,
    }
)
CODE_RELATIONS = frozenset(
    {
        RelationKind.IMPORTS,
        RelationKind.CALLS,
        RelationKind.DEFINES,
        RelationKind.INHERITS,
        RelationKind.REFERENCES,
        RelationKind.CONTAINS,
    }
)
PROJECTION_RELATIONS = frozenset({RelationKind.DOCUMENTS})

NODE_KINDS_BY_SOURCE: dict[GraphSourceKind, frozenset[NodeKind]] = {
    GraphSourceKind.KNOWLEDGE: KNOWLEDGE_NODE_KINDS,
    GraphSourceKind.CODE: CODE_NODE_KINDS,
    GraphSourceKind.PROJECTION: frozenset(),
}
RELATIONS_BY_SOURCE: dict[GraphSourceKind, frozenset[RelationKind]] = {
    GraphSourceKind.KNOWLEDGE: KNOWLEDGE_RELATIONS,
    GraphSourceKind.CODE: CODE_RELATIONS,
    GraphSourceKind.PROJECTION: PROJECTION_RELATIONS,
}


class Confidence(StrEnum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    DECLARED = "declared"


class GraphSource(LocalContractModel):
    """Identifies which provider run produced a graph. Knowledge and code
    sources stay separate; only a `projection` source may relate them, and only
    through explicitly declared relations."""

    source_id: Identifier
    kind: GraphSourceKind
    provider_id: Identifier
    workspace_id: UUID
    generated_at: UtcDatetime
    index_fingerprint: Sha256Hex | None = None
    member_sources: list[Identifier] = Field(default=[], max_length=2)

    @model_validator(mode="after")
    def _members(self) -> Self:
        if self.kind is GraphSourceKind.PROJECTION:
            if len(set(self.member_sources)) != 2:
                raise ValueError("a projection source names exactly two distinct member sources")
        elif self.member_sources:
            raise ValueError("only a projection source has member sources")
        return self


class GraphProvenance(LocalContractModel):
    """Required on every node and edge: where the fact comes from and how
    sure the extractor is. Facts without provenance are not representable."""

    source_id: Identifier
    extractor: Identifier
    confidence: Confidence
    evidence: LocalResourceUri | None = None

    @model_validator(mode="after")
    def _inferred_needs_evidence(self) -> Self:
        if self.confidence is Confidence.INFERRED and self.evidence is None:
            raise ValueError("an inferred fact must point at its evidence")
        return self


class GraphNodeRef(LocalContractModel):
    source_id: Identifier
    node_id: OpaqueId


class GraphNode(LocalContractModel):
    node_id: OpaqueId
    kind: NodeKind
    label: ShortText
    uri: LocalResourceUri | None = None
    provenance: GraphProvenance
    metadata: BoundedMetadata = {}


class GraphEdge(LocalContractModel):
    edge_id: OpaqueId
    kind: RelationKind
    source: GraphNodeRef
    target: GraphNodeRef
    provenance: GraphProvenance
    metadata: BoundedMetadata = {}


class GraphCounts(LocalContractModel):
    nodes: int = Field(ge=0)
    edges: int = Field(ge=0)
    total_nodes: int | None = Field(default=None, ge=0)
    total_edges: int | None = Field(default=None, ge=0)


class GraphPage(LocalContractModel):
    """One bounded slice of one source's graph. Edges may point outside the
    page only at nodes listed in `frontier` (loaded lazily on expansion): a
    dangling reference anywhere else is a defect, not an implicit relation."""

    source: GraphSource
    nodes: list[GraphNode] = Field(default=[], max_length=MAX_PAGE_LIMIT)
    edges: list[GraphEdge] = Field(default=[], max_length=MAX_PAGE_LIMIT * 2)
    frontier: list[GraphNodeRef] = Field(default=[], max_length=MAX_PAGE_LIMIT)
    next_cursor: OpaqueId | None = None
    truncated: bool = False
    counts: GraphCounts

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        source = self.source
        allowed_nodes = NODE_KINDS_BY_SOURCE[source.kind]
        allowed_relations = RELATIONS_BY_SOURCE[source.kind]
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("duplicate node ids in page")
        edge_ids = {edge.edge_id for edge in self.edges}
        if len(edge_ids) != len(self.edges):
            raise ValueError("duplicate edge ids in page")
        for node in self.nodes:
            if node.kind not in allowed_nodes:
                raise ValueError(f"node kind {node.kind.value} not allowed in {source.kind.value}")
            if node.provenance.source_id != source.source_id:
                raise ValueError("node provenance names another source")
        frontier = {(ref.source_id, ref.node_id) for ref in self.frontier}
        for edge in self.edges:
            if edge.kind not in allowed_relations:
                raise ValueError(
                    f"relation {edge.kind.value} not allowed in {source.kind.value} graph"
                )
            if edge.provenance.source_id != source.source_id:
                raise ValueError("edge provenance names another source")
            self._check_endpoints(edge, node_ids, frontier)
        if self.counts.nodes != len(self.nodes) or self.counts.edges != len(self.edges):
            raise ValueError("counts must describe the page content")
        if self.next_cursor is None and self.truncated and not self.frontier:
            raise ValueError("a truncated page offers a cursor or a frontier")
        return self

    def _check_endpoints(
        self, edge: GraphEdge, node_ids: set[str], frontier: set[tuple[str, str]]
    ) -> None:
        source = self.source
        if source.kind is GraphSourceKind.PROJECTION:
            ends = {edge.source.source_id, edge.target.source_id}
            if ends != set(source.member_sources):
                raise ValueError("a projection edge links its two member sources")
            return
        for end in (edge.source, edge.target):
            if end.source_id != source.source_id:
                raise ValueError("cross-source edge outside a projection source")
            if end.node_id not in node_ids and (end.source_id, end.node_id) not in frontier:
                raise ValueError(f"edge endpoint {end.node_id} is neither loaded nor on frontier")


class GraphDirection(StrEnum):
    OUT = "out"
    IN = "in"
    BOTH = "both"


class GraphPageRequest(LocalContractModel):
    workspace_id: UUID
    limit: int = Field(default=100, ge=1, le=MAX_PAGE_LIMIT)
    cursor: OpaqueId | None = None
    node_kinds: list[NodeKind] = Field(default=[], max_length=8)


class GraphExpandRequest(LocalContractModel):
    workspace_id: UUID
    node: GraphNodeRef
    direction: GraphDirection = GraphDirection.BOTH
    relations: list[RelationKind] = Field(default=[], max_length=10)
    limit: int = Field(default=50, ge=1, le=MAX_PAGE_LIMIT)
    cursor: OpaqueId | None = None
    depth: Literal[1] = 1
