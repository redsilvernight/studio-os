from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.graph import (
    DependenciesResult,
    GraphifyGraphProvider,
    GraphNode,
    GraphProvider,
    GraphQueryResult,
    RelatedSymbolsResult,
    RelevantFilesResult,
)
from studio_client.knowledge.index import KnowledgeIndex
from studio_client.knowledge.markdown import ParsedMarkdown, parse_markdown
from studio_client.knowledge.memory import (
    DEFAULT_EXCERPT_CHARS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_READ_CHARS,
    MemoryNoteHit,
    MemoryProposal,
    MemoryProvider,
    MemoryReadResult,
    MemorySearchResult,
    VaultMemoryProvider,
)
from studio_client.knowledge.obsidian import (
    ObsidianProbe,
    detect_obsidian,
    open_vault_in_obsidian,
)
from studio_client.knowledge.provider import (
    KnowledgeMemoryProvider,
    VaultKnowledgeProvider,
    disabled_knowledge_status,
)
from studio_client.knowledge.scope import ScopePolicy
from studio_client.knowledge.service import (
    KnowledgeService,
    knowledge_service_from_workspace,
    knowledge_vault_root,
)
from studio_client.knowledge.vault import VaultState, initialize_vault, vault_state

# `studio_client.knowledge.watch` is deliberately NOT imported here: it pulls the
# daemon's watcher/outbox machinery, and importing `studio_client.knowledge`
# must stay free of network and credential code (DEC-0047). The daemon imports
# it explicitly.
__all__ = [
    "KnowledgeError",
    "ScopePolicy",
    "MemoryNoteHit",
    "MemorySearchResult",
    "MemoryReadResult",
    "MemoryProposal",
    "MemoryProvider",
    "VaultMemoryProvider",
    "GraphNode",
    "GraphQueryResult",
    "RelevantFilesResult",
    "DependenciesResult",
    "RelatedSymbolsResult",
    "GraphProvider",
    "GraphifyGraphProvider",
    "DEFAULT_MAX_RESULTS",
    "DEFAULT_EXCERPT_CHARS",
    "DEFAULT_READ_CHARS",
    "KnowledgeIndex",
    "ParsedMarkdown",
    "parse_markdown",
    "VaultState",
    "initialize_vault",
    "vault_state",
    "ObsidianProbe",
    "detect_obsidian",
    "open_vault_in_obsidian",
    "VaultKnowledgeProvider",
    "KnowledgeMemoryProvider",
    "disabled_knowledge_status",
    "KnowledgeService",
    "knowledge_service_from_workspace",
    "knowledge_vault_root",
]
