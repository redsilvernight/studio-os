from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from studio_contracts.local.bridge import (
    BridgeCancel,
    BridgeErrorMessage,
    BridgeEvent,
    BridgeEventName,
    BridgeProgress,
    BridgeRequest,
    BridgeResponse,
    ComponentStateChanged,
)
from studio_contracts.local.code_graph import CodeGraphStatus, CodeSymbolRef, CodeSymbolResult
from studio_contracts.local.common import (
    ComponentId,
    ComponentState,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
    LocalResourceKind,
    build_local_uri,
)
from studio_contracts.local.daemon_control import (
    CrashInfo,
    DaemonAction,
    DaemonControlOutcome,
    DaemonControlRequest,
    DaemonControlResult,
    DaemonHealth,
    DaemonHealthRequest,
    DaemonInstanceRef,
    DaemonOwnership,
    DaemonRunState,
    DaemonStatus,
    OutboxSummary,
    RuntimeServiceCondition,
    RuntimeServiceHealth,
    RuntimeServiceId,
    decide_outbox_replay,
    instance_lock_key,
)
from studio_contracts.local.graph import (
    Confidence,
    GraphCounts,
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
    RelationKind,
)
from studio_contracts.local.handshake import (
    HandshakeRequest,
    OptionalComponentStatus,
    PeerInfo,
    PeerRole,
    ProtocolRange,
    ProtocolVersion,
    negotiate,
)
from studio_contracts.local.harness import (
    ChangeKind,
    ChangeScope,
    HarnessApplyRequest,
    HarnessApplyResult,
    HarnessChange,
    HarnessDetectResult,
    HarnessPlan,
    HarnessState,
    HarnessStatus,
    HarnessVerifyResult,
    VerifyState,
)
from studio_contracts.local.identity import (
    HumanIdentity,
    IdentityBinding,
    IdentityEnrollOutcome,
    IdentityEnrollResult,
    IdentityView,
    MachineIdentity,
    ProfileRef,
    SecretKind,
    SecretReference,
    SecretReferenceStatus,
    SecretStatus,
    SecretStore,
    partition_key,
)
from studio_contracts.local.knowledge import (
    KnowledgeDocumentRef,
    KnowledgeInitVaultRequest,
    KnowledgeInitVaultResult,
    KnowledgeIntegration,
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeStatus,
    KnowledgeVaultState,
)
from studio_contracts.local.provider import IndexInfo, IndexState, ProviderInfo
from studio_contracts.local.publication import (
    DEFAULT_PUBLICATION_POLICY,
    ComponentStatusSummary,
    LocalDataClass,
    PublicationOutcome,
    PublicationPlan,
    PublicationResult,
    SharedStatusSummary,
)
from studio_contracts.local.workspace import (
    CodeGraphConfig,
    GitState,
    IndexLocation,
    KnowledgeConfig,
    LocalFeatures,
    LocalWorkspaceConfig,
    RepoRoot,
    WatcherConfig,
    WorkspaceAction,
    WorkspaceConfirmRootsRequest,
    WorkspaceConfirmRootsResult,
    WorkspaceGitStatus,
    WorkspaceHealth,
    WorkspaceRoots,
    WorkspaceSaveConfigRequest,
    WorkspaceStatus,
)

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=2)

WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_ID = UUID("33333333-3333-4333-8333-333333333333")
MACHINE_ID = UUID("44444444-4444-4444-8444-444444444444")
INSTANCE_ID = UUID("55555555-5555-4555-8555-555555555555")
OTHER_MACHINE_ID = UUID("66666666-6666-4666-8666-666666666666")

PROFILE = ProfileRef(profile_id="default", server_origin="https://studio.example.test")
OTHER_PROFILE = ProfileRef(profile_id="staging", server_origin="https://staging.example.test")

CORRELATION = "corr-0001"
KNOWLEDGE_SOURCE_ID = "knowledge-main"
CODE_SOURCE_ID = "code-main"
PROJECTION_SOURCE_ID = "projection-main"
CODE_PROVIDER_ID = "graphify"
KNOWLEDGE_PROVIDER_ID = "markdown-files"

DESKTOP_CAPABILITIES = [
    "code_graph.graph",
    "code_graph.index",
    "code_graph.read",
    "daemon.control",
    "daemon.health",
    "harness.apply",
    "harness.plan",
    "harness.read",
    "harness.verify",
    "identity.enroll",
    "identity.view",
    "knowledge.graph",
    "knowledge.index",
    "knowledge.init",
    "knowledge.read",
    "publication.plan",
    "publication.publish",
    "workspace.config",
]
REQUIRED_CAPABILITIES = ["daemon.control", "identity.view", "workspace.config"]
KNOWLEDGE_CAPABILITIES = [
    "knowledge.graph",
    "knowledge.index",
    "knowledge.init",
    "knowledge.read",
]
CODE_GRAPH_CAPABILITIES = ["code_graph.graph", "code_graph.index", "code_graph.read"]
HARNESS_CAPABILITIES = ["harness.apply", "harness.plan", "harness.read", "harness.verify"]


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def error(
    code: LocalErrorCode,
    component: ComponentId,
    message: str,
    *,
    retryable: bool = False,
    correlation_id: str | None = None,
    **details: str | int | bool,
) -> LocalError:
    return LocalError(
        code=code,
        message=message,
        component=component,
        retryable=retryable,
        details=dict(details),
        correlation_id=correlation_id,
    )


def _range(minimum: tuple[int, int], maximum: tuple[int, int]) -> ProtocolRange:
    return ProtocolRange(
        minimum=ProtocolVersion(major=minimum[0], minor=minimum[1]),
        maximum=ProtocolVersion(major=maximum[0], minor=maximum[1]),
    )


def desktop_peer(
    protocol: ProtocolRange | None = None,
    *,
    required: list[str] | None = None,
) -> PeerInfo:
    return PeerInfo(
        role=PeerRole.DESKTOP,
        protocol=protocol or _range((1, 0), (1, 0)),
        component_version="0.1.0",
        capabilities=DESKTOP_CAPABILITIES,
        required_capabilities=REQUIRED_CAPABILITIES if required is None else required,
        optional_capabilities=[
            *CODE_GRAPH_CAPABILITIES,
            *HARNESS_CAPABILITIES,
            *KNOWLEDGE_CAPABILITIES,
            "daemon.health",
            "publication.plan",
            "publication.publish",
        ],
    )


def _component(
    component: ComponentId, state: ComponentState, provider: str | None, provides: list[str]
) -> OptionalComponentStatus:
    return OptionalComponentStatus(
        component=component, state=state, provider_id=provider, provides=provides
    )


def daemon_peer(
    *,
    protocol: ProtocolRange | None = None,
    protocol_id: str = "studio.local",
    drop: frozenset[str] = frozenset(),
    code_graph_state: ComponentState = ComponentState.READY,
) -> PeerInfo:
    components = [
        _component(
            ComponentId.KNOWLEDGE,
            ComponentState.READY,
            KNOWLEDGE_PROVIDER_ID,
            KNOWLEDGE_CAPABILITIES,
        ),
        _component(
            ComponentId.CODE_GRAPH, code_graph_state, CODE_PROVIDER_ID, CODE_GRAPH_CAPABILITIES
        ),
        _component(
            ComponentId.HARNESS, ComponentState.READY, "harness-alpha", HARNESS_CAPABILITIES
        ),
    ]
    served = {
        name
        for component in components
        if component.state in (ComponentState.READY, ComponentState.STALE)
        for name in component.provides
    }
    base = [
        *REQUIRED_CAPABILITIES,
        "daemon.health",
        "publication.plan",
        "publication.publish",
    ]
    offered = sorted((set(base) | served) - drop)
    return PeerInfo(
        role=PeerRole.DAEMON,
        protocol_id=protocol_id,
        protocol=protocol or _range((1, 0), (1, 0)),
        component_version="0.1.0",
        capabilities=offered,
        required_capabilities=[],
        optional_components=components,
    )


def running_daemon_status(
    *, ownership: DaemonOwnership = DaemonOwnership.DESKTOP_STARTED, pending: int = 3
) -> DaemonStatus:
    binding = IdentityBinding(
        server_origin=PROFILE.server_origin,
        profile_id=PROFILE.profile_id,
        machine_id=MACHINE_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
    )
    return DaemonStatus(
        state=DaemonRunState.RUNNING,
        instance=DaemonInstanceRef(
            instance_id=INSTANCE_ID,
            profile=PROFILE,
            lock_key=instance_lock_key(PROFILE),
            pid=4242,
            ownership=ownership,
            daemon_version="0.1.0",
            started_at=EARLIER,
        ),
        negotiated=ProtocolVersion(major=1, minor=0),
        outbox=OutboxSummary(
            binding=binding,
            partition_key=partition_key(binding),
            pending_count=pending,
            oldest_pending_at=EARLIER if pending else None,
        ),
    )


def _control_request(action: DaemonAction) -> DaemonControlRequest:
    return DaemonControlRequest(action=action, profile=PROFILE)


def secret_reference(profile: ProfileRef = PROFILE) -> SecretReference:
    return SecretReference(
        ref_id="sr-machine-default",
        kind=SecretKind.MACHINE_CREDENTIAL,
        store=SecretStore.OS_KEYRING,
        lookup_key="studio-os.machine.default",
        profile=profile,
    )


def _secret_status(
    status: SecretStatus,
    code: LocalErrorCode | None,
    *,
    profile: ProfileRef = PROFILE,
    retryable: bool = False,
) -> SecretReferenceStatus:
    return SecretReferenceStatus(
        reference=secret_reference(profile),
        status=status,
        checked_at=NOW,
        error=None
        if code is None
        else error(
            code, ComponentId.SECRET_STORE, f"Secret is {status.value}.", retryable=retryable
        ),
    )


HUMAN = HumanIdentity(
    user_id=USER_ID,
    display_name="Alex Developer",
    profile=PROFILE,
    session_expires_at=NOW + timedelta(hours=8),
)
MACHINE = MachineIdentity(
    machine_id=MACHINE_ID,
    machine_name="dev-workstation",
    profile=PROFILE,
    registered_at=EARLIER,
)


def _identity_view(secret: SecretReferenceStatus) -> IdentityView:
    return IdentityView(profile=PROFILE, human=HUMAN, machine=MACHINE, secrets=[secret])


def workspace_config(*, knowledge: bool = True, code_graph: bool = True) -> LocalWorkspaceConfig:
    return LocalWorkspaceConfig(
        workspace_id=WORKSPACE_ID,
        profile=PROFILE,
        project_id=PROJECT_ID,
        project_slug="demo-game",
        roots=WorkspaceRoots(
            workspace_root="C:/Work/demo-game",
            repo_roots=[RepoRoot(name="game", path="C:/Work/demo-game/game")],
        ),
        features=LocalFeatures(
            knowledge=knowledge, code_graph=code_graph, harness=True, watchers=True
        ),
        knowledge=KnowledgeConfig(
            provider_id=KNOWLEDGE_PROVIDER_ID,
            content_root="vault",
            index=IndexLocation(directory_name="knowledge-index"),
            integrations=["note-editor"],
        ),
        code_graph=CodeGraphConfig(
            provider_id=CODE_PROVIDER_ID,
            repo_names=["game"],
            languages=["python", "gdscript"],
            exclude_globs=["**/generated/**"],
            index=IndexLocation(directory_name="code-index"),
        ),
        watchers=WatcherConfig(),
        secret_references=[secret_reference()],
        created_at=EARLIER,
        updated_at=NOW,
    )


def _workspace_status(
    health: WorkspaceHealth,
    action: WorkspaceAction,
    code: LocalErrorCode | None,
    *,
    with_config: bool = False,
    candidate_root: str | None = None,
) -> WorkspaceStatus:
    return WorkspaceStatus(
        workspace_id=WORKSPACE_ID,
        health=health,
        action=action,
        config=workspace_config() if with_config else None,
        candidate_root=candidate_root,
        error=None
        if code is None
        else error(code, ComponentId.WORKSPACE, f"Workspace is {health.value}."),
    )


KNOWLEDGE_PROVIDER = ProviderInfo(
    provider_id=KNOWLEDGE_PROVIDER_ID,
    display_name="Markdown files",
    provider_version="1.0.0",
    capabilities=KNOWLEDGE_CAPABILITIES,
)
CODE_PROVIDER = ProviderInfo(
    provider_id=CODE_PROVIDER_ID,
    display_name="Code graph adapter",
    provider_version="0.4.1",
    capabilities=CODE_GRAPH_CAPABILITIES,
)


def _index(
    state: IndexState, *, items: int | None = None, progress: int | None = None
) -> IndexInfo:
    built = state in (IndexState.READY, IndexState.STALE)
    return IndexInfo(
        state=state,
        built_at=EARLIER if built else None,
        source_fingerprint=sha(f"src-{state.value}") if built else None,
        item_count=items,
        progress_percent=progress,
    )


def _knowledge_status(
    state: ComponentState,
    *,
    provider: ProviderInfo | None = KNOWLEDGE_PROVIDER,
    index: IndexInfo | None = None,
    err: LocalError | None = None,
    integration_state: ComponentState = ComponentState.NOT_INSTALLED,
) -> KnowledgeStatus:
    return KnowledgeStatus(
        workspace_id=WORKSPACE_ID,
        state=state,
        provider=provider,
        index=index,
        integrations=[KnowledgeIntegration(integration_id="note-editor", state=integration_state)],
        error=err,
    )


def _code_status(
    state: ComponentState,
    *,
    provider: ProviderInfo | None = CODE_PROVIDER,
    index: IndexInfo | None = None,
    err: LocalError | None = None,
    unsupported: list[str] | None = None,
) -> CodeGraphStatus:
    return CodeGraphStatus(
        workspace_id=WORKSPACE_ID,
        state=state,
        provider=provider,
        index=index,
        languages=["python", "gdscript"] if provider is not None else [],
        unsupported_languages=unsupported or [],
        error=err,
    )


def _provenance(
    source_id: str,
    extractor: str,
    confidence: Confidence = Confidence.EXTRACTED,
    evidence: str | None = None,
) -> GraphProvenance:
    return GraphProvenance(
        source_id=source_id, extractor=extractor, confidence=confidence, evidence=evidence
    )


def _source(source_id: str, kind: GraphSourceKind, provider_id: str, **extra: Any) -> GraphSource:
    return GraphSource(
        source_id=source_id,
        kind=kind,
        provider_id=provider_id,
        workspace_id=WORKSPACE_ID,
        generated_at=NOW,
        index_fingerprint=sha(f"index-{source_id}"),
        **extra,
    )


def _page(
    source: GraphSource,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    *,
    frontier: list[GraphNodeRef] | None = None,
    next_cursor: str | None = None,
    truncated: bool = False,
    total_nodes: int | None = None,
) -> GraphPage:
    return GraphPage(
        source=source,
        nodes=nodes,
        edges=edges,
        frontier=frontier or [],
        next_cursor=next_cursor,
        truncated=truncated,
        counts=GraphCounts(nodes=len(nodes), edges=len(edges), total_nodes=total_nodes),
    )


def _knowledge_uri(path: str) -> str:
    return build_local_uri(LocalResourceKind.KNOWLEDGE, WORKSPACE_ID, path)


def _code_uri(path: str, fragment: str | None = None) -> str:
    return build_local_uri(LocalResourceKind.CODE, WORKSPACE_ID, path, fragment=fragment)


def knowledge_graph_page() -> GraphPage:
    prov = _provenance(KNOWLEDGE_SOURCE_ID, "markdown_links")
    nodes = [
        GraphNode(
            node_id="doc-intro",
            kind=NodeKind.DOCUMENT,
            label="Introduction",
            uri=_knowledge_uri("notes/intro.md"),
            provenance=prov,
        ),
        GraphNode(
            node_id="doc-design",
            kind=NodeKind.DOCUMENT,
            label="Game design",
            uri=_knowledge_uri("notes/design.md"),
            provenance=prov,
        ),
        GraphNode(
            node_id="doc-combat",
            kind=NodeKind.DOCUMENT,
            label="Combat rules",
            uri=_knowledge_uri("notes/combat.md"),
            provenance=prov,
        ),
        GraphNode(node_id="tag-mechanics", kind=NodeKind.TAG, label="mechanics", provenance=prov),
    ]

    def edge(edge_id: str, kind: RelationKind, source: str, target: str) -> GraphEdge:
        return GraphEdge(
            edge_id=edge_id,
            kind=kind,
            source=GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id=source),
            target=GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id=target),
            provenance=prov,
        )

    edges = [
        edge("e1", RelationKind.LINKS_TO, "doc-intro", "doc-design"),
        edge("e2", RelationKind.LINKS_TO, "doc-design", "doc-combat"),
        edge("e3", RelationKind.TAGGED_WITH, "doc-combat", "tag-mechanics"),
    ]
    source = _source(KNOWLEDGE_SOURCE_ID, GraphSourceKind.KNOWLEDGE, KNOWLEDGE_PROVIDER_ID)
    return _page(source, nodes, edges, total_nodes=4)


def _knowledge_node(
    node_id: str,
    kind: NodeKind,
    label: str,
    path: str | None,
    extractor: str,
    evidence_path: str | None = None,
) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        kind=kind,
        label=label,
        uri=None if path is None else _knowledge_uri(path),
        provenance=_provenance(
            KNOWLEDGE_SOURCE_ID,
            extractor,
            evidence=None if evidence_path is None else _knowledge_uri(evidence_path),
        ),
    )


def empty_knowledge_graph_page() -> GraphPage:
    """A connected but empty vault: a source with no node and no edge."""
    source = _source(KNOWLEDGE_SOURCE_ID, GraphSourceKind.KNOWLEDGE, KNOWLEDGE_PROVIDER_ID)
    return _page(source, [], [], total_nodes=0)


def knowledge_links_graph_page() -> GraphPage:
    """Links and tags as the index demonstrates them, each with its extractor."""
    nodes = [
        _knowledge_node(
            "doc-a", NodeKind.DOCUMENT, "Alpha", "notes/alpha.md", "markdown_documents"
        ),
        _knowledge_node("doc-b", NodeKind.DOCUMENT, "Beta", "notes/beta.md", "markdown_documents"),
        _knowledge_node(
            "head-a",
            NodeKind.HEADING,
            "Overview",
            "notes/alpha.md",
            "markdown_headings",
            "notes/alpha.md",
        ),
        _knowledge_node(
            "tag-a", NodeKind.TAG, "mechanics", None, "markdown_tags", "notes/alpha.md"
        ),
    ]

    def edge(
        edge_id: str, kind: RelationKind, source: str, target: str, extractor: str, evidence: str
    ) -> GraphEdge:
        return GraphEdge(
            edge_id=edge_id,
            kind=kind,
            source=GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id=source),
            target=GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id=target),
            provenance=_provenance(
                KNOWLEDGE_SOURCE_ID, extractor, evidence=_knowledge_uri(evidence)
            ),
        )

    edges = [
        edge("k1", RelationKind.CONTAINS, "doc-a", "head-a", "markdown_headings", "notes/alpha.md"),
        edge("k2", RelationKind.LINKS_TO, "doc-a", "doc-b", "markdown_links", "notes/beta.md"),
        edge("k3", RelationKind.TAGGED_WITH, "doc-a", "tag-a", "markdown_tags", "notes/alpha.md"),
    ]
    source = _source(KNOWLEDGE_SOURCE_ID, GraphSourceKind.KNOWLEDGE, KNOWLEDGE_PROVIDER_ID)
    return _page(source, nodes, edges, total_nodes=4)


def knowledge_partial_graph_page() -> GraphPage:
    """A bounded slice: one loaded node, one edge whose far end sits on the
    frontier, and a cursor for the next page."""
    nodes = [
        _knowledge_node("doc-a", NodeKind.DOCUMENT, "Alpha", "notes/alpha.md", "markdown_documents")
    ]
    edges = [
        GraphEdge(
            edge_id="k1",
            kind=RelationKind.LINKS_TO,
            source=GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id="doc-a"),
            target=GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id="doc-b"),
            provenance=_provenance(
                KNOWLEDGE_SOURCE_ID, "markdown_links", evidence=_knowledge_uri("notes/beta.md")
            ),
        )
    ]
    source = _source(KNOWLEDGE_SOURCE_ID, GraphSourceKind.KNOWLEDGE, KNOWLEDGE_PROVIDER_ID)
    return _page(
        source,
        nodes,
        edges,
        frontier=[GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id="doc-b")],
        next_cursor="n:1",
        truncated=True,
        total_nodes=3,
    )


def knowledge_after_deletion_graph_page() -> GraphPage:
    """After a document was deleted, its node and every edge pointing at it are
    gone: the remaining graph is smaller, never a dangling reference."""
    nodes = [
        _knowledge_node(
            "doc-a", NodeKind.DOCUMENT, "Alpha", "notes/alpha.md", "markdown_documents"
        ),
        _knowledge_node(
            "head-a",
            NodeKind.HEADING,
            "Overview",
            "notes/alpha.md",
            "markdown_headings",
            "notes/alpha.md",
        ),
    ]
    edges = [
        GraphEdge(
            edge_id="k1",
            kind=RelationKind.CONTAINS,
            source=GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id="doc-a"),
            target=GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id="head-a"),
            provenance=_provenance(
                KNOWLEDGE_SOURCE_ID, "markdown_headings", evidence=_knowledge_uri("notes/alpha.md")
            ),
        )
    ]
    source = _source(KNOWLEDGE_SOURCE_ID, GraphSourceKind.KNOWLEDGE, KNOWLEDGE_PROVIDER_ID)
    return _page(source, nodes, edges, total_nodes=2)


def _code_nodes_and_edges() -> tuple[list[GraphNode], list[GraphEdge]]:
    prov = _provenance(CODE_SOURCE_ID, "ast")
    nodes = [
        GraphNode(
            node_id="file-main",
            kind=NodeKind.FILE,
            label="main.py",
            uri=_code_uri("game/main.py"),
            provenance=prov,
        ),
        GraphNode(
            node_id="fn-main",
            kind=NodeKind.FUNCTION,
            label="main",
            uri=_code_uri("game/main.py", "L3-L12"),
            provenance=prov,
        ),
        GraphNode(
            node_id="fn-step",
            kind=NodeKind.FUNCTION,
            label="step",
            uri=_code_uri("game/main.py", "L15-L20"),
            provenance=prov,
        ),
        GraphNode(
            node_id="cls-player",
            kind=NodeKind.CLASS,
            label="Player",
            uri=_code_uri("game/player.py", "L1-L40"),
            provenance=prov,
        ),
    ]

    def edge(
        edge_id: str, kind: RelationKind, source: str, target: str, provenance: GraphProvenance
    ) -> GraphEdge:
        return GraphEdge(
            edge_id=edge_id,
            kind=kind,
            source=GraphNodeRef(source_id=CODE_SOURCE_ID, node_id=source),
            target=GraphNodeRef(source_id=CODE_SOURCE_ID, node_id=target),
            provenance=provenance,
        )

    inferred = _provenance(
        CODE_SOURCE_ID, "call_resolver", Confidence.INFERRED, _code_uri("game/main.py", "L8-L8")
    )
    edges = [
        edge("c1", RelationKind.CONTAINS, "file-main", "fn-main", prov),
        edge("c2", RelationKind.CONTAINS, "file-main", "fn-step", prov),
        edge("c3", RelationKind.CALLS, "fn-main", "fn-step", inferred),
        edge("c4", RelationKind.REFERENCES, "fn-step", "cls-player", prov),
    ]
    return nodes, edges


def code_graph_page() -> GraphPage:
    nodes, edges = _code_nodes_and_edges()
    source = _source(CODE_SOURCE_ID, GraphSourceKind.CODE, CODE_PROVIDER_ID)
    return _page(source, nodes, edges, total_nodes=4)


def partial_code_graph_page() -> GraphPage:
    nodes, edges = _code_nodes_and_edges()
    prov = _provenance(CODE_SOURCE_ID, "ast")
    outside = GraphNodeRef(source_id=CODE_SOURCE_ID, node_id="fn-physics-step")
    edges.append(
        GraphEdge(
            edge_id="c5",
            kind=RelationKind.CALLS,
            source=GraphNodeRef(source_id=CODE_SOURCE_ID, node_id="fn-step"),
            target=outside,
            provenance=prov,
        )
    )
    source = _source(CODE_SOURCE_ID, GraphSourceKind.CODE, CODE_PROVIDER_ID)
    return _page(
        source,
        nodes,
        edges,
        frontier=[outside],
        next_cursor="cursor-2",
        truncated=True,
        total_nodes=1250,
    )


def empty_graph_page() -> GraphPage:
    return _page(_source(CODE_SOURCE_ID, GraphSourceKind.CODE, CODE_PROVIDER_ID), [], [])


def projection_graph_page() -> GraphPage:
    prov = _provenance(
        PROJECTION_SOURCE_ID,
        "declared_link",
        Confidence.DECLARED,
        _knowledge_uri("notes/combat.md"),
    )
    source = _source(
        PROJECTION_SOURCE_ID,
        GraphSourceKind.PROJECTION,
        "projection-rules",
        member_sources=[KNOWLEDGE_SOURCE_ID, CODE_SOURCE_ID],
    )
    edge = GraphEdge(
        edge_id="x1",
        kind=RelationKind.DOCUMENTS,
        source=GraphNodeRef(source_id=KNOWLEDGE_SOURCE_ID, node_id="doc-combat"),
        target=GraphNodeRef(source_id=CODE_SOURCE_ID, node_id="fn-step"),
        provenance=prov,
    )
    return _page(source, [], [edge])


def _search_result() -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        hits=[
            KnowledgeSearchHit(
                document=KnowledgeDocumentRef(
                    uri=_knowledge_uri("notes/combat.md"),
                    title="Combat rules",
                    content_hash=sha("combat"),
                    modified_at=EARLIER,
                ),
                score=0.87,
                snippet="Damage is resolved once per turn.",
            )
        ],
        index_state=ComponentState.READY,
    )


def _harness_status(state: HarnessState, **extra: Any) -> HarnessStatus:
    return HarnessStatus(
        adapter_id="harness-alpha-adapter",
        harness_id="harness-alpha",
        display_name="Harness Alpha",
        state=state,
        **extra,
    )


def _harness_plan() -> HarnessPlan:
    return HarnessPlan(
        plan_id="plan-0001",
        adapter_id="harness-alpha-adapter",
        workspace_id=WORKSPACE_ID,
        changes=[
            HarnessChange(
                change_id="chg-1",
                kind=ChangeKind.CREATE,
                target=".studio/harness/rules.md",
                summary="Add Studio OS working rules",
                after_hash=sha("rules-v1"),
            ),
            HarnessChange(
                change_id="chg-2",
                kind=ChangeKind.MODIFY,
                target=".studio/harness/index.md",
                summary="Register the rules file",
                before_hash=sha("index-v1"),
                after_hash=sha("index-v2"),
            ),
            HarnessChange(
                change_id="chg-3",
                kind=ChangeKind.CREATE,
                target=".config/harness-alpha/config.json",
                scope=ChangeScope.USER,
                summary="Declare Studio OS with a dedicated credential",
                after_hash=sha("entry-v1"),
            ),
        ],
        plan_hash=sha("plan-0001"),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )


def _publication_plan() -> PublicationPlan:
    return PublicationPlan(
        plan_id="pub-0001",
        summary=SharedStatusSummary(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            protocol_version="1.0.0",
            components=[
                ComponentStatusSummary(
                    component=ComponentId.KNOWLEDGE,
                    state=ComponentState.READY,
                    provider_id=KNOWLEDGE_PROVIDER_ID,
                    item_count=42,
                ),
                ComponentStatusSummary(
                    component=ComponentId.CODE_GRAPH,
                    state=ComponentState.STALE,
                    provider_id=CODE_PROVIDER_ID,
                    item_count=1250,
                ),
            ],
            generated_at=NOW,
        ),
        included=[],
        plan_hash=sha("pub-0001"),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        excluded_classes=sorted(LocalDataClass),
    )


def _bridge_request(command: str, payload: dict[str, Any]) -> BridgeRequest:
    return BridgeRequest.model_validate(
        {
            "message_id": "req-0001",
            "correlation_id": CORRELATION,
            "sent_at": NOW,
            "command": command,
            "payload": payload,
        }
    )


def _dump(model: LocalContractModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _handshake_request(peer: PeerInfo | None = None) -> HandshakeRequest:
    return HandshakeRequest(peer=peer or desktop_peer())


@dataclass(frozen=True)
class LocalFixture:
    name: str
    model: LocalContractModel

    @property
    def model_name(self) -> str:
        return type(self.model).__name__


def build_fixtures() -> list[LocalFixture]:
    fixtures: dict[str, LocalContractModel] = {}

    request = _handshake_request()
    fixtures["runtime.handshake.request"] = request
    fixtures["runtime.handshake.compatible"] = negotiate(
        request, daemon_peer(), correlation_id=CORRELATION
    )
    fixtures["runtime.handshake.compatible_degraded"] = negotiate(
        request,
        daemon_peer(code_graph_state=ComponentState.NOT_INSTALLED, drop=frozenset()),
        correlation_id=CORRELATION,
    )
    fixtures["runtime.handshake.daemon_too_old"] = negotiate(
        _handshake_request(desktop_peer(_range((2, 0), (2, 1)))),
        daemon_peer(),
        correlation_id=CORRELATION,
    )
    fixtures["runtime.handshake.desktop_too_old"] = negotiate(
        request,
        daemon_peer(protocol=_range((2, 0), (2, 3))),
        correlation_id=CORRELATION,
    )
    fixtures["runtime.handshake.capability_missing"] = negotiate(
        request,
        daemon_peer(drop=frozenset({"workspace.config"})),
        correlation_id=CORRELATION,
    )
    fixtures["runtime.handshake.protocol_incompatible"] = negotiate(
        request, daemon_peer(protocol_id="other.local"), correlation_id=CORRELATION
    )

    running = running_daemon_status()
    fixtures["daemon.status.running"] = running
    fixtures["daemon.health.request"] = DaemonHealthRequest(profile=PROFILE)
    fixtures["daemon.health.running"] = DaemonHealth(
        observed_at=NOW,
        status=running,
        heartbeat=RuntimeServiceHealth(
            service=RuntimeServiceId.HEARTBEAT,
            state=ComponentState.STALE,
            condition=RuntimeServiceCondition.SERVER_UNAVAILABLE,
            last_attempt_at=NOW,
            last_success_at=EARLIER,
            error=error(
                LocalErrorCode.DAEMON_UNAVAILABLE,
                ComponentId.DAEMON,
                "The server is temporarily unavailable.",
                retryable=True,
            ),
        ),
        git_watchers=[
            RuntimeServiceHealth(
                service=RuntimeServiceId.GIT_WATCHER,
                instance_key="watch-01",
                state=ComponentState.READY,
                condition=RuntimeServiceCondition.HEALTHY,
                last_attempt_at=NOW,
                last_success_at=NOW,
            )
        ],
        outbox_replay=RuntimeServiceHealth(
            service=RuntimeServiceId.OUTBOX_REPLAY,
            state=ComponentState.READY,
            condition=RuntimeServiceCondition.HEALTHY,
            last_attempt_at=NOW,
            last_success_at=NOW,
        ),
        providers=[
            OptionalComponentStatus(
                component=ComponentId.KNOWLEDGE,
                state=ComponentState.READY,
                provider_id=KNOWLEDGE_PROVIDER_ID,
                provides=KNOWLEDGE_CAPABILITIES,
            )
        ],
    )
    fixtures["daemon.status.stopped"] = DaemonStatus(state=DaemonRunState.STOPPED)
    fixtures["daemon.status.recovering"] = DaemonStatus(
        state=DaemonRunState.RECOVERING, instance=running.instance, outbox=running.outbox
    )
    crash = CrashInfo(
        crashed_at=NOW,
        exit_code=139,
        recoveries_attempted=2,
        error=error(
            LocalErrorCode.DAEMON_CRASHED, ComponentId.DAEMON, "The daemon exited unexpectedly."
        ),
    )
    fixtures["daemon.status.crashed"] = DaemonStatus(state=DaemonRunState.CRASHED, last_crash=crash)
    fixtures["daemon.control.start_ok"] = DaemonControlResult(
        action=DaemonAction.START, outcome=DaemonControlOutcome.OK, status=running
    )
    fixtures["daemon.control.stop_ok"] = DaemonControlResult(
        action=DaemonAction.STOP,
        outcome=DaemonControlOutcome.OK,
        status=DaemonStatus(state=DaemonRunState.STOPPED),
    )
    fixtures["daemon.control.already_running"] = DaemonControlResult(
        action=DaemonAction.START,
        outcome=DaemonControlOutcome.ALREADY_RUNNING,
        status=running_daemon_status(ownership=DaemonOwnership.EXTERNAL),
        error=error(
            LocalErrorCode.DAEMON_ALREADY_RUNNING,
            ComponentId.DAEMON,
            "A daemon is already running for this profile; attach to it.",
        ),
    )
    fixtures["daemon.control.unavailable"] = DaemonControlResult(
        action=DaemonAction.STATUS,
        outcome=DaemonControlOutcome.UNAVAILABLE,
        status=DaemonStatus(state=DaemonRunState.UNAVAILABLE),
        error=error(
            LocalErrorCode.DAEMON_UNAVAILABLE,
            ComponentId.DAEMON,
            "The daemon does not answer.",
            retryable=True,
        ),
    )
    fixtures["daemon.control.incompatible"] = DaemonControlResult(
        action=DaemonAction.ATTACH,
        outcome=DaemonControlOutcome.INCOMPATIBLE,
        status=DaemonStatus(state=DaemonRunState.INCOMPATIBLE),
        error=error(
            LocalErrorCode.PROTOCOL_INCOMPATIBLE,
            ComponentId.DAEMON,
            "The running daemon speaks an incompatible protocol.",
        ),
    )
    fixtures["daemon.control.request_stop"] = _control_request(DaemonAction.STOP)
    active = IdentityBinding(
        server_origin=PROFILE.server_origin,
        profile_id=PROFILE.profile_id,
        machine_id=MACHINE_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
    )
    foreign = active.model_copy(update={"machine_id": OTHER_MACHINE_ID})
    fixtures["daemon.outbox.replay_allowed"] = decide_outbox_replay(active, active)
    fixtures["daemon.outbox.replay_refused_identity_mismatch"] = decide_outbox_replay(
        foreign, active, correlation_id=CORRELATION
    )

    fixtures["workspace.config.full"] = workspace_config()
    fixtures["workspace.config.minimal"] = workspace_config(
        knowledge=False, code_graph=False
    ).model_copy(
        update={
            "features": LocalFeatures(),
            "knowledge": None,
            "code_graph": None,
            "watchers": None,
        }
    )
    stored = workspace_config()
    moved_roots = WorkspaceRoots(
        workspace_root="D:/Work/demo-game",
        repo_roots=[RepoRoot(name="game", path="D:/Work/demo-game/game")],
    )
    fixtures["workspace.save.unchanged"] = WorkspaceSaveConfigRequest(
        config=stored, current_roots=stored.roots, expected_updated_at=stored.updated_at
    )
    fixtures["workspace.save.root_transition"] = WorkspaceSaveConfigRequest(
        config=stored.model_copy(update={"roots": moved_roots}),
        current_roots=stored.roots,
        expected_updated_at=stored.updated_at,
        root_confirmation_id="rc-demo-1",
    )
    fixtures["workspace.save.initial"] = WorkspaceSaveConfigRequest(
        config=stored, current_roots=None, root_confirmation_id="rc-demo-2"
    )
    fixtures["workspace.confirm.request"] = WorkspaceConfirmRootsRequest(roots=stored.roots)
    fixtures["workspace.confirm.result"] = WorkspaceConfirmRootsResult(
        root_confirmation_id="rc-demo-3", expires_in_s=600
    )
    fixtures["workspace.git.valid"] = WorkspaceGitStatus(
        workspace_id=WORKSPACE_ID,
        state=GitState.VALID,
        branch="main",
        remote="https://example.test/demo-game.git",
    )
    fixtures["workspace.git.not_a_repo"] = WorkspaceGitStatus(
        workspace_id=WORKSPACE_ID, state=GitState.NOT_A_REPO
    )
    fixtures["workspace.git.git_absent"] = WorkspaceGitStatus(
        workspace_id=WORKSPACE_ID, state=GitState.GIT_ABSENT
    )
    fixtures["workspace.status.valid"] = _workspace_status(
        WorkspaceHealth.VALID, WorkspaceAction.NONE, None, with_config=True
    )
    fixtures["workspace.status.config_missing"] = _workspace_status(
        WorkspaceHealth.CONFIG_MISSING,
        WorkspaceAction.CREATE_CONFIG,
        LocalErrorCode.WORKSPACE_CONFIG_MISSING,
    )
    fixtures["workspace.status.config_invalid"] = _workspace_status(
        WorkspaceHealth.CONFIG_INVALID,
        WorkspaceAction.REPAIR_CONFIG,
        LocalErrorCode.WORKSPACE_CONFIG_INVALID,
    )
    fixtures["workspace.status.moved"] = _workspace_status(
        WorkspaceHealth.MOVED,
        WorkspaceAction.CONFIRM_RELOCATION,
        LocalErrorCode.WORKSPACE_MOVED,
        candidate_root="D:/Projects/demo-game",
    )
    fixtures["workspace.status.inaccessible"] = _workspace_status(
        WorkspaceHealth.INACCESSIBLE,
        WorkspaceAction.GRANT_ACCESS,
        LocalErrorCode.WORKSPACE_INACCESSIBLE,
    )
    fixtures["workspace.status.project_unavailable"] = _workspace_status(
        WorkspaceHealth.PROJECT_UNAVAILABLE,
        WorkspaceAction.DETACH_WORKSPACE,
        LocalErrorCode.PROJECT_UNAVAILABLE,
    )

    fixtures["identity.view.ok"] = _identity_view(_secret_status(SecretStatus.PRESENT, None))
    fixtures["identity.view.secret_absent"] = _identity_view(
        _secret_status(SecretStatus.ABSENT, LocalErrorCode.SECRET_ABSENT)
    )
    fixtures["identity.view.secret_inaccessible"] = _identity_view(
        _secret_status(SecretStatus.INACCESSIBLE, LocalErrorCode.SECRET_INACCESSIBLE)
    )
    fixtures["identity.view.secret_revoked"] = _identity_view(
        _secret_status(SecretStatus.REVOKED, LocalErrorCode.SECRET_REVOKED)
    )
    fixtures["identity.view.keyring_unavailable"] = _identity_view(
        _secret_status(
            SecretStatus.KEYRING_UNAVAILABLE, LocalErrorCode.KEYRING_UNAVAILABLE, retryable=True
        )
    )
    fixtures["identity.view.wrong_profile"] = _identity_view(
        _secret_status(
            SecretStatus.WRONG_PROFILE, LocalErrorCode.WRONG_PROFILE, profile=OTHER_PROFILE
        )
    )
    # A5 enrollment (DEC-0130): results only. A request carries the write-only
    # human session, which no fixture may hold.
    fixtures["identity.enroll.enrolled"] = IdentityEnrollResult(
        outcome=IdentityEnrollOutcome.ENROLLED,
        machine_id=MACHINE_ID,
        view=_identity_view(_secret_status(SecretStatus.PRESENT, None)),
    )
    fixtures["identity.enroll.already_enrolled"] = IdentityEnrollResult(
        outcome=IdentityEnrollOutcome.ALREADY_ENROLLED,
        view=_identity_view(_secret_status(SecretStatus.PRESENT, None)),
    )

    fixtures["knowledge.status.disabled"] = _knowledge_status(
        ComponentState.DISABLED,
        provider=None,
        err=error(LocalErrorCode.FEATURE_DISABLED, ComponentId.KNOWLEDGE, "Knowledge is disabled."),
    )
    fixtures["knowledge.status.indexing"] = _knowledge_status(
        ComponentState.INDEXING, index=_index(IndexState.INDEXING, progress=40)
    )
    fixtures["knowledge.status.ready"] = _knowledge_status(
        ComponentState.READY, index=_index(IndexState.READY, items=42)
    )
    fixtures["knowledge.status.stale"] = _knowledge_status(
        ComponentState.STALE, index=_index(IndexState.STALE, items=42)
    )
    fixtures["knowledge.status.unavailable"] = _knowledge_status(
        ComponentState.UNAVAILABLE,
        index=_index(IndexState.ABSENT),
        err=error(
            LocalErrorCode.INDEX_ABSENT,
            ComponentId.KNOWLEDGE,
            "The knowledge index has not been built yet.",
        ),
    )
    fixtures["knowledge.status.error"] = _knowledge_status(
        ComponentState.ERROR,
        index=_index(IndexState.CORRUPT),
        err=error(
            LocalErrorCode.INDEX_CORRUPT,
            ComponentId.KNOWLEDGE,
            "The knowledge index is corrupt and must be rebuilt.",
        ),
    )
    fixtures["knowledge.status.permission_denied"] = _knowledge_status(
        ComponentState.PERMISSION_DENIED,
        err=error(
            LocalErrorCode.PERMISSION_DENIED,
            ComponentId.KNOWLEDGE,
            "The vault folder cannot be read.",
        ),
    )
    fixtures["knowledge.init_vault.request"] = KnowledgeInitVaultRequest(
        workspace_id=WORKSPACE_ID,
        confirmed=True,
    )
    fixtures["knowledge.init_vault.result"] = KnowledgeInitVaultResult(
        workspace_id=WORKSPACE_ID,
        state_before=KnowledgeVaultState.MISSING,
        created=[
            ".studio",
            ".studio/vault.json",
            "README.md",
            "conventions",
            "decisions",
            "projects",
            "tasks",
        ],
    )
    fixtures["knowledge.search.request"] = KnowledgeSearchRequest(
        workspace_id=WORKSPACE_ID, query="combat rules"
    )
    fixtures["knowledge.search.result"] = _search_result()

    fixtures["code_graph.status.not_installed"] = _code_status(
        ComponentState.NOT_INSTALLED,
        provider=None,
        err=error(
            LocalErrorCode.PROVIDER_NOT_INSTALLED,
            ComponentId.CODE_GRAPH,
            "No code graph provider is installed.",
        ),
    )
    fixtures["code_graph.status.disabled"] = _code_status(
        ComponentState.DISABLED,
        provider=None,
        err=error(
            LocalErrorCode.FEATURE_DISABLED, ComponentId.CODE_GRAPH, "Code graph is disabled."
        ),
    )
    fixtures["code_graph.status.provider_incompatible"] = _code_status(
        ComponentState.INCOMPATIBLE,
        err=error(
            LocalErrorCode.PROVIDER_INCOMPATIBLE,
            ComponentId.CODE_GRAPH,
            "The installed provider is not compatible with this client.",
            found_version="0.2.0",
            required_range=">=0.4.0",
        ),
    )
    fixtures["code_graph.status.index_absent"] = _code_status(
        ComponentState.UNAVAILABLE,
        index=_index(IndexState.ABSENT),
        err=error(
            LocalErrorCode.INDEX_ABSENT, ComponentId.CODE_GRAPH, "The index has not been built yet."
        ),
    )
    fixtures["code_graph.status.indexing"] = _code_status(
        ComponentState.INDEXING, index=_index(IndexState.INDEXING, progress=65)
    )
    fixtures["code_graph.status.ready"] = _code_status(
        ComponentState.READY, index=_index(IndexState.READY, items=1250)
    )
    fixtures["code_graph.status.stale"] = _code_status(
        ComponentState.STALE, index=_index(IndexState.STALE, items=1250)
    )
    fixtures["code_graph.status.corrupt"] = _code_status(
        ComponentState.ERROR,
        index=_index(IndexState.ABSENT).model_copy(update={"state": IndexState.CORRUPT}),
        err=error(
            LocalErrorCode.INDEX_CORRUPT,
            ComponentId.CODE_GRAPH,
            "The index is corrupt and must be rebuilt.",
        ),
    )
    fixtures["code_graph.status.unsupported_language"] = _code_status(
        ComponentState.READY, index=_index(IndexState.READY, items=800), unsupported=["cobol"]
    )
    fixtures["code_graph.symbols.result"] = CodeSymbolResult(
        symbols=[
            CodeSymbolRef(
                node_id="fn-step",
                kind=NodeKind.FUNCTION,
                name="step",
                uri=_code_uri("game/main.py", "L15-L20"),
            )
        ],
        index_state=IndexState.READY,
    )

    fixtures["graph.knowledge.small"] = knowledge_graph_page()
    fixtures["graph.knowledge.empty"] = empty_knowledge_graph_page()
    fixtures["graph.knowledge.links"] = knowledge_links_graph_page()
    fixtures["graph.knowledge.partial"] = knowledge_partial_graph_page()
    fixtures["graph.knowledge.after_deletion"] = knowledge_after_deletion_graph_page()
    fixtures["graph.code.small"] = code_graph_page()
    fixtures["graph.code.partial"] = partial_code_graph_page()
    fixtures["graph.empty"] = empty_graph_page()
    fixtures["graph.projection.cross_source"] = projection_graph_page()
    fixtures["graph.page.request"] = GraphPageRequest(workspace_id=WORKSPACE_ID, limit=100)
    fixtures["graph.expand.request"] = GraphExpandRequest(
        workspace_id=WORKSPACE_ID,
        node=GraphNodeRef(source_id=CODE_SOURCE_ID, node_id="fn-step"),
    )

    fixtures["harness.status.not_detected"] = _harness_status(
        HarnessState.NOT_DETECTED,
        error=error(
            LocalErrorCode.PROVIDER_NOT_INSTALLED, ComponentId.HARNESS, "Harness not found."
        ),
    )
    fixtures["harness.status.detected"] = _harness_status(
        HarnessState.DETECTED, detected_version="1.2.0", capabilities=["harness.plan"]
    )
    fixtures["harness.status.configured"] = _harness_status(
        HarnessState.CONFIGURED,
        detected_version="1.2.0",
        capabilities=["harness.apply", "harness.plan"],
        managed_files=[".studio/harness/rules.md"],
    )
    fixtures["harness.status.incompatible"] = _harness_status(
        HarnessState.INCOMPATIBLE,
        detected_version="0.3.0",
        error=error(
            LocalErrorCode.PROVIDER_INCOMPATIBLE,
            ComponentId.HARNESS,
            "Harness version unsupported.",
        ),
    )
    fixtures["harness.status.error"] = _harness_status(
        HarnessState.ERROR,
        error=error(
            LocalErrorCode.INTERNAL_ERROR,
            ComponentId.HARNESS,
            "Harness detection failed.",
            retryable=True,
        ),
    )
    fixtures["harness.detect.result"] = HarnessDetectResult(
        harnesses=[_harness_status(HarnessState.DETECTED, detected_version="1.2.0")]
    )
    plan = _harness_plan()
    fixtures["harness.plan.preview"] = plan
    fixtures["harness.apply.request"] = HarnessApplyRequest(
        plan_id=plan.plan_id, plan_hash=plan.plan_hash, confirmed=True
    )
    fixtures["harness.apply.result"] = HarnessApplyResult(
        plan_id=plan.plan_id,
        applied=["chg-1", "chg-2"],
        rollback_id="rb-0001",
        state=HarnessState.CONFIGURED,
    )
    fixtures["harness.verify.result.token_missing"] = HarnessVerifyResult(
        adapter_id="harness-alpha-adapter",
        state=VerifyState.TOKEN_MISSING,
        mcp_url="https://studio.example/mcp",
        details={"reason": "token_missing"},
    )
    fixtures["harness.verify.result.verified"] = HarnessVerifyResult(
        adapter_id="harness-alpha-adapter",
        state=VerifyState.VERIFIED,
        mcp_url="https://studio.example/mcp",
        details={"method": "studio_get_projects"},
    )

    fixtures["publication.plan.preview"] = _publication_plan()
    fixtures["publication.result.published"] = PublicationResult(
        plan_id="pub-0001", outcome=PublicationOutcome.PUBLISHED, published_at=NOW
    )
    fixtures["publication.result.transport_unavailable"] = PublicationResult(
        plan_id="pub-0001",
        outcome=PublicationOutcome.TRANSPORT_UNAVAILABLE,
        error=error(
            LocalErrorCode.NOT_SUPPORTED,
            ComponentId.BRIDGE,
            "Publication transport is not available yet.",
        ),
    )
    fixtures["publication.policy.default"] = DEFAULT_PUBLICATION_POLICY

    fixtures["bridge.request.handshake"] = _bridge_request("runtime.handshake", _dump(request))
    search = fixtures["knowledge.search.request"]
    fixtures["bridge.request.knowledge_search"] = _bridge_request("knowledge.search", _dump(search))
    fixtures["bridge.response.knowledge_search"] = BridgeResponse.model_validate(
        {
            "message_id": "res-0001",
            "correlation_id": CORRELATION,
            "sent_at": NOW,
            "request_id": "req-0001",
            "command": "knowledge.search",
            "payload": _dump(_search_result()),
        }
    )
    fixtures["bridge.error.capability_missing"] = BridgeErrorMessage(
        message_id="err-0001",
        correlation_id=CORRELATION,
        sent_at=NOW,
        request_id="req-0001",
        error=error(
            LocalErrorCode.CAPABILITY_MISSING,
            ComponentId.BRIDGE,
            "This command needs a capability that was not negotiated.",
            correlation_id=CORRELATION,
            capability="code_graph.read",
        ),
    )
    fixtures["bridge.event.daemon_state_changed"] = BridgeEvent.model_validate(
        {
            "message_id": "evt-0001",
            "correlation_id": "corr-events",
            "sent_at": NOW,
            "event": BridgeEventName.DAEMON_STATE_CHANGED.value,
            "payload": _dump(running),
        }
    )
    fixtures["bridge.event.component_state_changed"] = BridgeEvent.model_validate(
        {
            "message_id": "evt-0002",
            "correlation_id": "corr-events",
            "sent_at": NOW,
            "event": BridgeEventName.COMPONENT_STATE_CHANGED.value,
            "payload": _dump(
                ComponentStateChanged(
                    component=ComponentId.CODE_GRAPH,
                    state=ComponentState.INDEXING,
                    workspace_id=WORKSPACE_ID,
                )
            ),
        }
    )
    fixtures["bridge.progress.reindex"] = BridgeProgress(
        message_id="prg-0001",
        correlation_id=CORRELATION,
        sent_at=NOW,
        request_id="req-0002",
        phase="parsing",
        completed=650,
        total=1250,
    )
    fixtures["bridge.cancel.reindex"] = BridgeCancel(
        message_id="cnl-0001", correlation_id=CORRELATION, sent_at=NOW, request_id="req-0002"
    )

    return [LocalFixture(name, model) for name, model in sorted(fixtures.items())]


@dataclass(frozen=True)
class InvalidFixture:
    name: str
    model_name: str
    data: dict[str, Any]
    reason: str


def _valid_data(name: str) -> dict[str, Any]:
    for fixture in build_fixtures():
        if fixture.name == name:
            return _dump(fixture.model)
    raise KeyError(name)


def _with(name: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    data = _valid_data(name)
    mutate(data)
    return data


def build_invalid_fixtures() -> list[InvalidFixture]:
    def add_field(key: str, value: object) -> Callable[[dict[str, Any]], None]:
        return lambda data: data.__setitem__(key, value)

    def remove_provenance(data: dict[str, Any]) -> None:
        del data["edges"][0]["provenance"]

    def grant_on_failure(data: dict[str, Any]) -> None:
        data["granted_capabilities"] = ["daemon.control"]

    def secret_detail(data: dict[str, Any]) -> None:
        data["error"]["details"] = {"api_key": "value"}

    def path_detail(data: dict[str, Any]) -> None:
        data["error"]["details"] = {"location": "C:/Users/dev/notes"}

    def traversal_uri(data: dict[str, Any]) -> None:
        data["hits"][0]["document"]["uri"] = (
            f"studio-local://knowledge/{WORKSPACE_ID}/../../secrets.md"
        )

    def code_uri_for_document(data: dict[str, Any]) -> None:
        data["hits"][0]["document"]["uri"] = _code_uri("game/main.py")

    def credential_in_snippet(data: dict[str, Any]) -> None:
        data["hits"][0]["snippet"] = (
            "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk"
        )

    def unconfirmed(data: dict[str, Any]) -> None:
        data["confirmed"] = False

    def wrong_action(data: dict[str, Any]) -> None:
        data["payload"]["action"] = "start"

    def forbidden_command(data: dict[str, Any]) -> None:
        data["command"] = "shell.exec"

    def edge_dangling(data: dict[str, Any]) -> None:
        data["edges"][0]["target"]["node_id"] = "missing-node"

    def relation_wrong_source(data: dict[str, Any]) -> None:
        data["edges"][0]["kind"] = "calls"

    def secret_config_field(data: dict[str, Any]) -> None:
        data["machine_token"] = "value"

    def relative_root(data: dict[str, Any]) -> None:
        data["roots"]["workspace_root"] = "demo-game"

    def drop_confirmation(data: dict[str, Any]) -> None:
        data["root_confirmation_id"] = None

    def stray_confirmation(data: dict[str, Any]) -> None:
        data["root_confirmation_id"] = "rc-stray"

    def revoked_without_error(data: dict[str, Any]) -> None:
        data["secrets"][0]["error"] = None

    return [
        InvalidFixture(
            "workspace.save.transition_unconfirmed",
            "WorkspaceSaveConfigRequest",
            _with("workspace.save.root_transition", drop_confirmation),
            "a root transition without confirmation is refused",
        ),
        InvalidFixture(
            "workspace.save.initial_unconfirmed",
            "WorkspaceSaveConfigRequest",
            _with("workspace.save.initial", drop_confirmation),
            "the first authorization of roots needs confirmation too",
        ),
        InvalidFixture(
            "workspace.save.confirmation_without_transition",
            "WorkspaceSaveConfigRequest",
            _with("workspace.save.unchanged", stray_confirmation),
            "a stable config carries no confirmation id",
        ),
        InvalidFixture(
            "workspace.config.secret_field",
            "LocalWorkspaceConfig",
            _with("workspace.config.full", secret_config_field),
            "unknown field: configuration never carries secret values",
        ),
        InvalidFixture(
            "workspace.config.relative_root",
            "LocalWorkspaceConfig",
            _with("workspace.config.full", relative_root),
            "roots must be absolute",
        ),
        InvalidFixture(
            "workspace.confirm.relative_root",
            "WorkspaceConfirmRootsRequest",
            _with("workspace.confirm.request", relative_root),
            "roots must be absolute",
        ),
        InvalidFixture(
            "secret.reference_with_value",
            "SecretReference",
            {**_dump(secret_reference()), "value": "hunter2"},
            "unknown field: a reference has no value",
        ),
        InvalidFixture(
            "identity.enroll.session_bad_shape",
            "IdentityEnrollRequest",
            {
                "profile": _dump(PROFILE),
                "human_session": "not a session value at all",
                "machine_name": "dev-workstation",
            },
            "the human session only holds token characters",
        ),
        InvalidFixture(
            "identity.enroll.session_too_short",
            "IdentityEnrollRequest",
            {"profile": _dump(PROFILE), "human_session": "short", "machine_name": "dev"},
            "the human session is at least 16 characters",
        ),
        InvalidFixture(
            "identity.enroll.enrolled_without_machine",
            "IdentityEnrollResult",
            {**_valid_data("identity.enroll.enrolled"), "machine_id": None},
            "an enrolled outcome names the new machine",
        ),
        InvalidFixture(
            "identity.view.revoked_without_error",
            "IdentityView",
            _with("identity.view.secret_revoked", revoked_without_error),
            "non-present secret requires a structured error",
        ),
        InvalidFixture(
            "bridge.request.forbidden_command",
            "BridgeRequest",
            _with("bridge.request.knowledge_search", forbidden_command),
            "command outside the allowlist",
        ),
        InvalidFixture(
            "bridge.request.unknown_field",
            "BridgeRequest",
            _with("bridge.request.knowledge_search", add_field("shell", "cmd")),
            "unknown envelope field",
        ),
        InvalidFixture(
            "bridge.request.payload_extra_field",
            "BridgeRequest",
            _with(
                "bridge.request.knowledge_search",
                lambda d: d["payload"].__setitem__("path", "C:/Windows"),
            ),
            "payload field outside the command schema",
        ),
        InvalidFixture(
            "bridge.request.action_mismatch",
            "BridgeRequest",
            {
                "message_id": "req-9",
                "correlation_id": CORRELATION,
                "sent_at": NOW.isoformat(),
                "command": "daemon.stop",
                "payload": _dump(_control_request(DaemonAction.STOP)),
            }
            | {"payload": {**_dump(_control_request(DaemonAction.STOP)), "action": "start"}},
            "daemon command and payload action must agree",
        ),
        InvalidFixture(
            "handshake.incompatible_grants_capability",
            "HandshakeResponse",
            _with("runtime.handshake.capability_missing", grant_on_failure),
            "an incompatible outcome grants nothing",
        ),
        InvalidFixture(
            "error.secret_detail_key",
            "BridgeErrorMessage",
            _with("bridge.error.capability_missing", secret_detail),
            "error details cannot name a secret",
        ),
        InvalidFixture(
            "error.path_detail_value",
            "BridgeErrorMessage",
            _with("bridge.error.capability_missing", path_detail),
            "error details cannot carry an absolute path",
        ),
        InvalidFixture(
            "knowledge.search.traversal_uri",
            "KnowledgeSearchResult",
            _with("knowledge.search.result", traversal_uri),
            "resource URI must be canonical",
        ),
        InvalidFixture(
            "knowledge.search.code_uri",
            "KnowledgeSearchResult",
            _with("knowledge.search.result", code_uri_for_document),
            "a knowledge document has a knowledge URI",
        ),
        InvalidFixture(
            "knowledge.search.credential_snippet",
            "KnowledgeSearchResult",
            _with("knowledge.search.result", credential_in_snippet),
            "credential-shaped content is refused",
        ),
        InvalidFixture(
            "graph.edge_without_provenance",
            "GraphPage",
            _with("graph.knowledge.small", remove_provenance),
            "provenance is required",
        ),
        InvalidFixture(
            "graph.edge_dangling",
            "GraphPage",
            _with("graph.knowledge.small", edge_dangling),
            "edge endpoint is neither loaded nor on the frontier",
        ),
        InvalidFixture(
            "graph.relation_wrong_source",
            "GraphPage",
            _with("graph.knowledge.small", relation_wrong_source),
            "a code relation is not valid in a knowledge graph",
        ),
        InvalidFixture(
            "harness.apply_unconfirmed",
            "HarnessApplyRequest",
            _with("harness.apply.request", unconfirmed),
            "apply requires explicit confirmation",
        ),
        InvalidFixture(
            "harness.verify.token_missing_with_error",
            "HarnessVerifyResult",
            _with(
                "harness.verify.result.token_missing",
                add_field(
                    "error",
                    _dump(error(LocalErrorCode.INTERNAL_ERROR, ComponentId.HARNESS, "x")),
                ),
            ),
            "a missing token is a condition, not a failure: it carries no error",
        ),
        InvalidFixture(
            "publication.publish_unconfirmed",
            "PublicationPublishRequest",
            {
                "plan_id": "pub-0001",
                "plan_hash": sha("pub-0001"),
                "confirmed": False,
            },
            "publication requires explicit confirmation",
        ),
    ]
