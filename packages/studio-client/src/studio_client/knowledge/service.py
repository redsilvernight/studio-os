from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from studio_contracts.local.workspace import LocalWorkspaceConfig

from studio_client.knowledge.index import KnowledgeIndex
from studio_client.knowledge.obsidian import ObsidianProbe
from studio_client.knowledge.provider import KnowledgeMemoryProvider, VaultKnowledgeProvider
from studio_client.knowledge.scope import ScopePolicy

INDEX_DIRECTORY_SUFFIX = "knowledge-index"


@dataclass(frozen=True)
class KnowledgeService:
    """A workspace's knowledge service: one vault, one derived index, one
    provider. Created only when the workspace turns the feature on."""

    workspace_id: UUID
    vault_root: Path
    provider: VaultKnowledgeProvider

    def memory_provider(self, *, allowed_prefixes: Sequence[str] = ()) -> KnowledgeMemoryProvider:
        """Agent-facing adapter. The scope is closed by default (DEC-0042):
        nothing is exposed until the caller names the prefixes it authorizes."""
        return KnowledgeMemoryProvider(self.provider, scope=ScopePolicy(tuple(allowed_prefixes)))

    def detach(self) -> bool:
        """Forget the derived index. Canonical Markdown is never deleted: the
        vault stays exactly as it was before Studi'OS ever opened it."""
        return self.provider.index.drop()


def knowledge_vault_root(config: LocalWorkspaceConfig) -> Path | None:
    """Resolve `KnowledgeConfig.content_root` inside the workspace root."""
    if config.knowledge is None:
        return None
    workspace_root = Path(config.roots.workspace_root)
    return workspace_root / PurePosixPath(config.knowledge.content_root)


def knowledge_service_from_workspace(
    config: LocalWorkspaceConfig,
    *,
    cache_dir: Path,
    clock: Callable[[], datetime] | None = None,
    obsidian: ObsidianProbe | None = None,
) -> KnowledgeService | None:
    """Build the knowledge service of a workspace, or `None` when the feature is
    off — in which case no index, no watcher and no service exist at all."""
    if not config.features.knowledge or config.knowledge is None:
        return None
    vault_root = knowledge_vault_root(config)
    if vault_root is None:
        return None
    directory_name = config.knowledge.index.directory_name
    index = KnowledgeIndex(
        cache_dir / directory_name,
        workspace_id=config.workspace_id,
        include_globs=config.knowledge.include_globs,
        exclude_globs=config.knowledge.exclude_globs,
    )
    provider = VaultKnowledgeProvider(
        workspace_id=config.workspace_id,
        vault_root=vault_root,
        index=index,
        provider_id=config.knowledge.provider_id,
        clock=clock,
        obsidian=obsidian,
        include_globs=config.knowledge.include_globs,
        exclude_globs=config.knowledge.exclude_globs,
    )
    return KnowledgeService(
        workspace_id=config.workspace_id, vault_root=vault_root, provider=provider
    )
