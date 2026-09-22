from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar
from uuid import UUID

from studio_contracts.local.code_graph import (
    CodeGraphStatus,
    CodeReindexRequest,
    CodeReindexResult,
    CodeSymbolQuery,
    CodeSymbolResult,
)
from studio_contracts.local.common import ComponentId, ComponentState, LocalError, LocalErrorCode
from studio_contracts.local.graph import GraphExpandRequest, GraphPage, GraphPageRequest
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessApplyResult,
    HarnessDetectResult,
    HarnessPlan,
    HarnessPreviewRequest,
    HarnessRollbackRequest,
    HarnessRollbackResult,
    HarnessStatus,
    HarnessStatusRequest,
)
from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.knowledge import (
    KnowledgeDocument,
    KnowledgeGetDocumentRequest,
    KnowledgeInitVaultRequest,
    KnowledgeInitVaultResult,
    KnowledgeReindexRequest,
    KnowledgeReindexResult,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeStatus,
    KnowledgeVaultState,
)
from studio_contracts.local.workspace import LocalWorkspaceConfig, WorkspaceScope

from studio_client.harness.backup import BackupStore
from studio_client.harness.base import system_env
from studio_client.harness.registry import HarnessRegistry, default_adapters
from studio_client.harness.service import (
    HarnessService,
    HarnessServiceError,
    WorkspaceInfo,
)
from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.provider import disabled_knowledge_status
from studio_client.knowledge.service import KnowledgeService, knowledge_service_from_workspace
from studio_client.knowledge.vault import VaultInitReport, initialize_vault
from studio_client.knowledge.watch import VaultIndexWatcher
from studio_client.watchers import GitChange

_LOGGER = logging.getLogger("studio_client.daemon.local_features")

_T = TypeVar("_T")

FEATURE_CAPABILITIES: tuple[str, ...] = (
    "knowledge.read",
    "knowledge.graph",
    "knowledge.index",
    "knowledge.init",
    "code_graph.read",
    "code_graph.graph",
    "code_graph.index",
    "harness.read",
    "harness.plan",
    "harness.apply",
)
MCP_PATH = "/mcp"

WorkspaceConfigSource = Callable[[ProfileRef], Sequence[LocalWorkspaceConfig]]
KnowledgeServiceFactory = Callable[[LocalWorkspaceConfig, Path], KnowledgeService | None]


class GitChangeLike(Protocol):
    @property
    def repo_path(self) -> Path: ...


class CodeGraphServiceLike(Protocol):
    async def configure(self, config: LocalWorkspaceConfig) -> None: ...

    async def status(self, workspace_id: UUID) -> CodeGraphStatus: ...

    async def reindex(self, request: CodeReindexRequest) -> CodeReindexResult: ...

    async def on_git_change(self, change: GitChangeLike) -> None: ...

    async def search_symbols(self, query: CodeSymbolQuery) -> CodeSymbolResult: ...

    async def graph_page(self, request: GraphPageRequest) -> GraphPage: ...

    async def graph_expand(self, request: GraphExpandRequest) -> GraphPage: ...

    async def wait_idle(self) -> None: ...

    async def close(self) -> None: ...


class LocalFeatureError(Exception):
    """A local feature failure carrying the structured error the daemon returns
    to the Desktop, so a precise state is never flattened into a generic
    `internal_error`."""

    def __init__(self, error: LocalError) -> None:
        super().__init__(error.message)
        self.error = error


def _error(
    component: ComponentId,
    code: LocalErrorCode,
    message: str,
    *,
    retryable: bool = False,
) -> LocalError:
    return LocalError(code=code, message=message, component=component, retryable=retryable)


_KNOWLEDGE_REASON_CODES: dict[str, LocalErrorCode] = {
    KnowledgeError.VAULT_MISSING: LocalErrorCode.WORKSPACE_INACCESSIBLE,
    KnowledgeError.VAULT_NOT_A_DIRECTORY: LocalErrorCode.WORKSPACE_INACCESSIBLE,
    KnowledgeError.INDEX_CORRUPT: LocalErrorCode.INDEX_CORRUPT,
    KnowledgeError.INVALID_FRONTMATTER: LocalErrorCode.INDEX_CORRUPT,
    KnowledgeError.GRAPH_MISSING: LocalErrorCode.INVALID_REQUEST,
    KnowledgeError.GRAPH_INVALID: LocalErrorCode.INVALID_REQUEST,
    KnowledgeError.REFRESH_UNSUPPORTED: LocalErrorCode.NOT_SUPPORTED,
    KnowledgeError.WRITE_UNSUPPORTED: LocalErrorCode.NOT_SUPPORTED,
    KnowledgeError.OUT_OF_SCOPE: LocalErrorCode.INVALID_REQUEST,
    KnowledgeError.NOT_FOUND: LocalErrorCode.INVALID_REQUEST,
    KnowledgeError.NOT_A_FILE: LocalErrorCode.INVALID_REQUEST,
}


def _knowledge_error(error: KnowledgeError) -> LocalFeatureError:
    return LocalFeatureError(
        _error(
            ComponentId.KNOWLEDGE,
            _KNOWLEDGE_REASON_CODES.get(error.reason, LocalErrorCode.INTERNAL_ERROR),
            "The knowledge source could not serve the request.",
        )
    )


def missing_knowledge_status(workspace_id: UUID) -> KnowledgeStatus:
    return KnowledgeStatus(
        workspace_id=workspace_id,
        state=ComponentState.UNAVAILABLE,
        error=_error(
            ComponentId.KNOWLEDGE,
            LocalErrorCode.WORKSPACE_CONFIG_MISSING,
            "This workspace is not configured on this machine.",
        ),
    )


def missing_code_graph_status(workspace_id: UUID) -> CodeGraphStatus:
    return CodeGraphStatus(
        workspace_id=workspace_id,
        state=ComponentState.UNAVAILABLE,
        error=_error(
            ComponentId.CODE_GRAPH,
            LocalErrorCode.WORKSPACE_CONFIG_MISSING,
            "This workspace is not configured on this machine.",
        ),
    )


class _FeatureLoop:
    """One asyncio loop for the local features, in its own thread: the daemon's
    bridge is synchronous, the code graph and the vault watcher are async, and
    the runtime's own loop belongs to the git watchers."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def running(self) -> bool:
        return self._loop is not None and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="studio-daemon-features", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=10)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                self._loop = None

    def submit(self, coroutine: Coroutine[Any, Any, _T], *, timeout: float) -> _T:
        loop = self._loop
        if loop is None:
            raise LocalFeatureError(
                _error(
                    ComponentId.DAEMON,
                    LocalErrorCode.DAEMON_UNAVAILABLE,
                    "The local feature runtime is not running.",
                    retryable=True,
                )
            )
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result(timeout)

    async def submit_async(self, coroutine: Coroutine[Any, Any, _T]) -> _T:
        loop = self._loop
        if loop is None:
            raise LocalFeatureError(
                _error(
                    ComponentId.DAEMON,
                    LocalErrorCode.DAEMON_UNAVAILABLE,
                    "The local feature runtime is not running.",
                    retryable=True,
                )
            )
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coroutine, loop))

    def stop(self) -> None:
        loop = self._loop
        thread = self._thread
        self._thread = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=10)


class LocalFeatureRegistry:
    """Per-workspace Knowledge and Code Graph services behind the local bridge.

    Canonical sources stay local (Markdown files, the Git working tree): the
    registry only owns derived, rebuildable indexes and never uploads anything.
    The Markdown files are never deleted, even when a workspace is dissociated.
    """

    def __init__(
        self,
        *,
        workspace_configs: WorkspaceConfigSource,
        cache_root: Path,
        code_graph_service: CodeGraphServiceLike | None = None,
        knowledge_factory: KnowledgeServiceFactory | None = None,
        vault_poll_seconds: float = 30.0,
        harness_backups_root: Path | None = None,
        harness_registry: HarnessRegistry | None = None,
        harness_env: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        self._workspace_configs = workspace_configs
        self._cache_root = cache_root
        self._code_graph = code_graph_service
        self._knowledge_factory = knowledge_factory or _default_knowledge_factory
        self._vault_poll_seconds = vault_poll_seconds
        self._loop = _FeatureLoop()
        self._lock = threading.RLock()
        self._profile: ProfileRef | None = None
        self._configs: dict[UUID, LocalWorkspaceConfig] = {}
        self._services: dict[UUID, KnowledgeService | None] = {}
        self._watchers: dict[UUID, asyncio.Task[None]] = {}
        self._started = False
        self._harness = HarnessService(
            harness_registry or HarnessRegistry(default_adapters()),
            BackupStore(harness_backups_root or cache_root.parent / "harness-backups"),
            self._harness_workspace,
            env=harness_env or system_env,
        )

    @property
    def started(self) -> bool:
        return self._started

    def start(self, profile: ProfileRef) -> None:
        with self._lock:
            self._profile = profile
            if self._started:
                return
            self._loop.start()
            self._started = True
        self.refresh(profile)

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._started = False
        if self._loop.running:
            self._loop.submit(self._shutdown(), timeout=15)
        self._loop.stop()
        with self._lock:
            self._configs.clear()
            self._services.clear()
            self._watchers.clear()

    async def _shutdown(self) -> None:
        for task in list(self._watchers.values()):
            task.cancel()
        if self._watchers:
            await asyncio.gather(*self._watchers.values(), return_exceptions=True)
        self._watchers.clear()
        if self._code_graph is not None:
            await self._code_graph.close()

    def refresh(self, profile: ProfileRef) -> None:
        with self._lock:
            if not self._started:
                return
        try:
            configs = list(self._workspace_configs(profile))
        except Exception:
            _LOGGER.warning("could not read the workspace configuration", exc_info=True)
            return
        self._loop.submit(self._reconcile(configs), timeout=60)

    async def refresh_async(self, profile: ProfileRef) -> None:
        with self._lock:
            if not self._started:
                return
        try:
            configs = list(await asyncio.to_thread(self._workspace_configs, profile))
        except Exception:
            _LOGGER.warning("could not read the workspace configuration", exc_info=True)
            return
        await self._loop.submit_async(self._reconcile(configs))

    async def _reconcile(self, configs: Sequence[LocalWorkspaceConfig]) -> None:
        desired = {config.workspace_id: config for config in configs}
        for workspace_id in list(self._services):
            if workspace_id not in desired:
                self._stop_watcher(workspace_id)
                self._services.pop(workspace_id, None)
                self._configs.pop(workspace_id, None)
        for workspace_id, config in desired.items():
            if self._configs.get(workspace_id) == config and workspace_id in self._services:
                continue
            self._stop_watcher(workspace_id)
            self._configs[workspace_id] = config
            service = self._knowledge_factory(config, self._cache_root / "knowledge")
            self._services[workspace_id] = service
            if service is not None:
                watcher = VaultIndexWatcher(
                    service.provider, interval_seconds=self._vault_poll_seconds
                )
                self._watchers[workspace_id] = asyncio.create_task(
                    watcher.run(), name=f"vault-watch-{workspace_id}"
                )
        if self._code_graph is not None:
            for config in desired.values():
                await self._code_graph.configure(config)

    def _stop_watcher(self, workspace_id: UUID) -> None:
        task = self._watchers.pop(workspace_id, None)
        if task is not None:
            task.cancel()

    def _resolve(self, workspace_id: UUID) -> None:
        """Re-read the workspace registry when an unknown workspace is asked
        for. Only ever called from the caller's thread, never from the feature
        loop (submitting to the loop from the loop itself would deadlock)."""
        if workspace_id in self._configs:
            return
        profile = self._profile
        if profile is not None:
            self.refresh(profile)

    def _knowledge(self, workspace_id: UUID) -> KnowledgeService | None:
        return self._services.get(workspace_id)

    def knowledge_status(self, request: WorkspaceScope) -> KnowledgeStatus:
        self._resolve(request.workspace_id)
        return self._loop.submit(self._knowledge_status(request.workspace_id), timeout=60)

    async def _knowledge_status(self, workspace_id: UUID) -> KnowledgeStatus:
        service = self._knowledge(workspace_id)
        if service is None:
            if workspace_id in self._configs:
                return disabled_knowledge_status(workspace_id)
            return missing_knowledge_status(workspace_id)
        try:
            return await asyncio.to_thread(service.provider.status)
        except KnowledgeError as error:
            raise _knowledge_error(error) from error

    def knowledge_init_vault(
        self, request: KnowledgeInitVaultRequest
    ) -> KnowledgeInitVaultResult:
        self._resolve(request.workspace_id)
        with self._lock:
            return self._loop.submit(self._knowledge_init_vault(request), timeout=60)

    async def _knowledge_init_vault(
        self, request: KnowledgeInitVaultRequest
    ) -> KnowledgeInitVaultResult:
        service = self._require_knowledge(request.workspace_id)
        config = self._configs[request.workspace_id]
        try:
            report = await asyncio.to_thread(_initialize_workspace_vault, config, service)
        except KnowledgeError as error:
            raise _knowledge_error(error) from error
        except OSError as error:
            raise LocalFeatureError(
                _error(
                    ComponentId.KNOWLEDGE,
                    LocalErrorCode.PERMISSION_DENIED,
                    "The knowledge folder could not be initialized.",
                )
            ) from error
        return KnowledgeInitVaultResult(
            workspace_id=request.workspace_id,
            state_before=KnowledgeVaultState(report.state_before.value),
            created=list(report.created),
            skipped=list(report.skipped),
        )

    def knowledge_search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        self._resolve(request.workspace_id)
        return self._loop.submit(self._knowledge_search(request), timeout=60)

    async def _knowledge_search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        service = self._require_knowledge(request.workspace_id)
        try:
            return await asyncio.to_thread(service.provider.search, request)
        except KnowledgeError as error:
            raise _knowledge_error(error) from error

    def knowledge_get_document(self, request: KnowledgeGetDocumentRequest) -> KnowledgeDocument:
        workspace_id = _uri_workspace(request.uri)
        if workspace_id is not None:
            self._resolve(workspace_id)
        return self._loop.submit(self._knowledge_get_document(request), timeout=60)

    async def _knowledge_get_document(
        self, request: KnowledgeGetDocumentRequest
    ) -> KnowledgeDocument:
        service = self._require_knowledge(_uri_workspace(request.uri))
        try:
            return await asyncio.to_thread(service.provider.get_document, request)
        except KnowledgeError as error:
            raise _knowledge_error(error) from error

    def knowledge_reindex(self, request: KnowledgeReindexRequest) -> KnowledgeReindexResult:
        self._resolve(request.workspace_id)
        return self._loop.submit(self._knowledge_reindex(request), timeout=600)

    async def _knowledge_reindex(self, request: KnowledgeReindexRequest) -> KnowledgeReindexResult:
        service = self._require_knowledge(request.workspace_id)
        try:
            return await asyncio.to_thread(service.provider.reindex, request)
        except KnowledgeError as error:
            raise _knowledge_error(error) from error

    def knowledge_graph_page(self, request: GraphPageRequest) -> GraphPage:
        self._resolve(request.workspace_id)
        return self._loop.submit(self._knowledge_graph_page(request), timeout=60)

    async def _knowledge_graph_page(self, request: GraphPageRequest) -> GraphPage:
        service = self._require_knowledge(request.workspace_id)
        try:
            return await asyncio.to_thread(service.provider.graph_page, request)
        except KnowledgeError as error:
            raise _knowledge_error(error) from error

    def knowledge_graph_expand(self, request: GraphExpandRequest) -> GraphPage:
        self._resolve(request.workspace_id)
        return self._loop.submit(self._knowledge_graph_expand(request), timeout=60)

    async def _knowledge_graph_expand(self, request: GraphExpandRequest) -> GraphPage:
        service = self._require_knowledge(request.workspace_id)
        try:
            return await asyncio.to_thread(service.provider.graph_expand, request)
        except KnowledgeError as error:
            raise _knowledge_error(error) from error

    def _require_knowledge(self, workspace_id: UUID | None) -> KnowledgeService:
        if workspace_id is None:
            raise LocalFeatureError(
                _error(ComponentId.KNOWLEDGE, LocalErrorCode.INVALID_REQUEST, "Unknown workspace.")
            )
        service = self._knowledge(workspace_id)
        if service is None:
            raise LocalFeatureError(
                _error(
                    ComponentId.KNOWLEDGE,
                    LocalErrorCode.FEATURE_DISABLED,
                    "The knowledge source is not enabled for this workspace.",
                )
            )
        return service

    def code_graph_status(self, request: WorkspaceScope) -> CodeGraphStatus:
        self._resolve(request.workspace_id)
        return self._loop.submit(self._code_graph_status(request.workspace_id), timeout=120)

    async def _code_graph_status(self, workspace_id: UUID) -> CodeGraphStatus:
        if workspace_id not in self._configs:
            return missing_code_graph_status(workspace_id)
        return await self._require_code_graph().status(workspace_id)

    def code_graph_reindex(self, request: CodeReindexRequest) -> CodeReindexResult:
        self._resolve(request.workspace_id)
        return self._loop.submit(self._code_graph_reindex_async(request), timeout=120)

    async def _code_graph_reindex_async(self, request: CodeReindexRequest) -> CodeReindexResult:
        if request.workspace_id not in self._configs:
            return CodeReindexResult(
                accepted=False,
                state=ComponentState.UNAVAILABLE,
                error=missing_code_graph_status(request.workspace_id).error,
            )
        return await self._require_code_graph().reindex(request)

    def code_graph_search_symbols(self, query: CodeSymbolQuery) -> CodeSymbolResult:
        self._resolve(query.workspace_id)
        return self._loop.submit(self._code_graph_search_async(query), timeout=120)

    async def _code_graph_search_async(self, query: CodeSymbolQuery) -> CodeSymbolResult:
        if query.workspace_id not in self._configs:
            raise LocalFeatureError(
                _error(
                    ComponentId.CODE_GRAPH,
                    LocalErrorCode.WORKSPACE_CONFIG_MISSING,
                    "This workspace is not configured on this machine.",
                )
            )
        return await self._query(self._require_code_graph().search_symbols(query))

    def code_graph_graph_page(self, request: GraphPageRequest) -> GraphPage:
        self._resolve(request.workspace_id)
        return self._loop.submit(self._code_graph_graph_page_async(request), timeout=120)

    async def _code_graph_graph_page_async(self, request: GraphPageRequest) -> GraphPage:
        if request.workspace_id not in self._configs:
            raise LocalFeatureError(
                _error(
                    ComponentId.CODE_GRAPH,
                    LocalErrorCode.WORKSPACE_CONFIG_MISSING,
                    "This workspace is not configured on this machine.",
                )
            )
        return await self._query(self._require_code_graph().graph_page(request))

    def code_graph_graph_expand(self, request: GraphExpandRequest) -> GraphPage:
        self._resolve(request.workspace_id)
        return self._loop.submit(self._code_graph_graph_expand_async(request), timeout=120)

    async def _code_graph_graph_expand_async(self, request: GraphExpandRequest) -> GraphPage:
        if request.workspace_id not in self._configs:
            raise LocalFeatureError(
                _error(
                    ComponentId.CODE_GRAPH,
                    LocalErrorCode.WORKSPACE_CONFIG_MISSING,
                    "This workspace is not configured on this machine.",
                )
            )
        return await self._query(self._require_code_graph().graph_expand(request))

    async def _query(self, awaitable: Awaitable[_T]) -> _T:
        try:
            return await awaitable
        except Exception as error:
            structured = getattr(error, "error", None)
            if isinstance(structured, LocalError):
                raise LocalFeatureError(structured) from error
            raise

    def _require_code_graph(self) -> CodeGraphServiceLike:
        if self._code_graph is None:
            raise LocalFeatureError(
                _error(
                    ComponentId.CODE_GRAPH,
                    LocalErrorCode.FEATURE_DISABLED,
                    "The code graph is not enabled on this daemon.",
                )
            )
        return self._code_graph

    def _harness_workspace(self, workspace_id: UUID) -> WorkspaceInfo | None:
        config = self._configs.get(workspace_id)
        if config is None:
            return None
        return WorkspaceInfo(
            workspace_id=workspace_id,
            root=Path(config.roots.workspace_root),
            mcp_url=str(config.profile.server_origin).rstrip("/") + MCP_PATH,
            harness_enabled=config.features.harness,
        )

    def _harness_call(self, workspace_id: UUID | None, call: Callable[[], _T]) -> _T:
        if workspace_id is not None:
            self._resolve(workspace_id)
        try:
            return call()
        except HarnessServiceError as error:
            raise LocalFeatureError(error.error) from error

    def harness_detect(self, request: WorkspaceScope) -> HarnessDetectResult:
        return self._harness_call(request.workspace_id, lambda: self._harness.detect(request))

    def harness_status(self, request: HarnessStatusRequest) -> HarnessStatus:
        return self._harness_call(request.workspace_id, lambda: self._harness.status(request))

    def harness_preview(self, request: HarnessPreviewRequest) -> HarnessPlan:
        return self._harness_call(request.workspace_id, lambda: self._harness.preview(request))

    def harness_apply(self, request: HarnessApplyRequest) -> HarnessApplyResult:
        return self._harness_call(None, lambda: self._harness.apply(request))

    def harness_rollback(self, request: HarnessRollbackRequest) -> HarnessRollbackResult:
        return self._harness_call(None, lambda: self._harness.rollback(request))

    async def on_git_change(self, change: GitChange) -> None:
        if not self._started or self._code_graph is None:
            return
        await self._loop.submit_async(self._code_graph.on_git_change(change))

    async def wait_idle(self) -> None:
        if self._code_graph is not None:
            await self._loop.submit_async(self._code_graph.wait_idle())


def _uri_workspace(uri: str) -> UUID | None:
    from studio_contracts.local.common import parse_local_uri

    try:
        return parse_local_uri(uri)[1]
    except ValueError:
        return None


def _default_knowledge_factory(
    config: LocalWorkspaceConfig, cache_dir: Path
) -> KnowledgeService | None:
    return knowledge_service_from_workspace(config, cache_dir=cache_dir)


def _initialize_workspace_vault(
    config: LocalWorkspaceConfig, service: KnowledgeService
) -> VaultInitReport:
    workspace_root = Path(config.roots.workspace_root)
    vault_root = service.vault_root
    try:
        relative = vault_root.relative_to(workspace_root)
    except ValueError as error:
        raise KnowledgeError(
            KnowledgeError.OUT_OF_SCOPE, "the vault must stay inside the workspace"
        ) from error
    current = workspace_root
    for part in relative.parts:
        current /= part
        if (current.exists() or current.is_symlink()) and _is_link_or_junction(current):
            raise KnowledgeError(
                KnowledgeError.OUT_OF_SCOPE, "the vault cannot traverse a link or junction"
            )
    try:
        vault_root.resolve(strict=False).relative_to(workspace_root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise KnowledgeError(
            KnowledgeError.OUT_OF_SCOPE, "the vault must stay inside the workspace"
        ) from error
    return initialize_vault(vault_root)


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    try:
        return bool(isjunction(path)) if isjunction is not None else False
    except OSError:
        return True
