from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Protocol
from uuid import UUID

from studio_contracts.local.code_graph import (
    CodeGraphStatus,
    CodeReindexMode,
    CodeReindexRequest,
    CodeReindexResult,
    CodeSymbolQuery,
    CodeSymbolResult,
)
from studio_contracts.local.common import ComponentState, LocalError, LocalErrorCode
from studio_contracts.local.graph import (
    GraphExpandRequest,
    GraphPage,
    GraphPageRequest,
    GraphSource,
    GraphSourceKind,
)
from studio_contracts.local.provider import IndexInfo, IndexState, ProviderInfo
from studio_contracts.local.workspace import (
    WORKSPACE_HEALTH_BEHAVIOR,
    LocalWorkspaceConfig,
    WorkspaceHealth,
    WorkspaceStatus,
)

from studio_code_graph.errors import CodeGraphQueryError, build_failure_error, make_error
from studio_code_graph.gitstate import ChangeSummary, RepoFiles, read_repo_files, summarize_change
from studio_code_graph.index import (
    CodeGraphIndex,
    InvalidCursorError,
    UnknownNodeError,
)
from studio_code_graph.paths import same_location
from studio_code_graph.provider import (
    BuildRequest,
    CodeGraphBuildError,
    CodeGraphProvider,
    ProbeState,
    ProviderProbe,
    RepoGraph,
)
from studio_code_graph.store import IndexStore, RepoSnapshot, StoreCorruptError

logger = logging.getLogger(__name__)

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
FileReader = Callable[[Path, frozenset[str], tuple[str, ...], tuple[str, ...]], RepoFiles | None]


class GitChangeLike(Protocol):
    """What the service needs from a Git watcher event: the repository that
    changed. `studio_client`'s `GitChange` satisfies it structurally."""

    @property
    def repo_path(self) -> Path: ...


@dataclass
class _Repo:
    name: str
    root: Path
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    languages: tuple[str, ...]
    extensions: frozenset[str]
    snapshot: RepoSnapshot | None = None
    corrupt: bool = False
    stale: bool = False
    missing: bool = False
    building: bool = False
    queued: bool = False
    rerun: bool = False
    full: bool = False
    deadline: float = 0.0
    failure: LocalError | None = None
    checked_at: float = -math.inf
    last_change: ChangeSummary | None = None
    pump: asyncio.Task[None] | None = None

    def same_setup(self, other: _Repo) -> bool:
        return (
            same_location(self.root, other.root)
            and self.include == other.include
            and self.exclude == other.exclude
            and self.languages == other.languages
        )


@dataclass
class _Workspace:
    workspace_id: UUID
    config: LocalWorkspaceConfig | None = None
    invalid: LocalErrorCode | None = None
    repos: dict[str, _Repo] = field(default_factory=dict)
    index: CodeGraphIndex | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def enabled(self) -> bool:
        return (
            self.config is not None
            and self.config.features.code_graph
            and self.config.code_graph is not None
        )


@dataclass(frozen=True)
class RepoReport:
    """Diagnostics beyond the contract: the last failure kept while a previous
    index is still served, what the last rebuild changed and what the provider
    facts dropped."""

    name: str
    phase: str
    node_count: int
    edge_count: int
    failure: LocalError | None
    last_change: ChangeSummary | None
    dropped: dict[str, int]


def _semver(version: str | None) -> str | None:
    return version if version is not None and _SEMVER.match(version) else None


def _now() -> datetime:
    return datetime.now(UTC)


class CodeGraphService:
    """Local Code Graph behind the provider boundary. It owns configuration,
    states, on-disk snapshots, the in-memory query index and Git invalidation;
    it depends only on `CodeGraphProvider`, never on a concrete engine."""

    def __init__(
        self,
        providers: Iterable[CodeGraphProvider],
        cache_root: Path,
        *,
        debounce_seconds: float = 2.0,
        build_timeout_seconds: float = 300.0,
        probe_ttl_seconds: float = 60.0,
        freshness_ttl_seconds: float = 5.0,
        max_concurrent_builds: int = 1,
        file_reader: FileReader = read_repo_files,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._providers = {provider.provider_id: provider for provider in providers}
        self._store = IndexStore(cache_root)
        self._debounce = debounce_seconds
        self._timeout = build_timeout_seconds
        self._probe_ttl = probe_ttl_seconds
        self._freshness_ttl = freshness_ttl_seconds
        self._slots = asyncio.Semaphore(max_concurrent_builds)
        self._read_files = file_reader
        self._clock = clock
        self._workspaces: dict[UUID, _Workspace] = {}
        self._probes: dict[str, tuple[float, ProviderProbe]] = {}
        self._closed = False

    async def configure(self, config: LocalWorkspaceConfig) -> None:
        ws = self._workspaces.setdefault(config.workspace_id, _Workspace(config.workspace_id))
        async with ws.lock:
            ws.config = config
            ws.invalid = None
            if not ws.enabled or config.code_graph is None:
                self._drop_repos(ws, ws.repos)
                ws.index = None
                return
            settings = config.code_graph
            provider = self._providers.get(settings.provider_id)
            desired = await self._desired_repos(config, provider)
            self._drop_repos(ws, [name for name in ws.repos if name not in desired])
            for name, fresh in desired.items():
                current = ws.repos.get(name)
                if current is not None and current.same_setup(fresh):
                    continue
                if current is not None:
                    self._drop_repos(ws, [name])
                await self._load_snapshot(ws, fresh)
                ws.repos[name] = fresh
            ws.index = self._make_index(ws)
            if provider is None:
                return
            probe = await self._probe(provider, force=True)
            if probe.state is not ProbeState.AVAILABLE:
                return
            for repo in ws.repos.values():
                await self._check_freshness(ws, repo, provider, probe, force=True)
                if repo.snapshot is None or repo.corrupt or repo.stale:
                    self._schedule(ws, repo, 0.0, full=repo.corrupt)

    async def apply_workspace_status(self, status: WorkspaceStatus) -> None:
        if status.health is WorkspaceHealth.VALID and status.config is not None:
            await self.configure(status.config)
            return
        ws = self._workspaces.setdefault(status.workspace_id, _Workspace(status.workspace_id))
        code = (
            WORKSPACE_HEALTH_BEHAVIOR[status.health][0] or LocalErrorCode.WORKSPACE_CONFIG_INVALID
        )
        async with ws.lock:
            ws.invalid = code
            for repo in ws.repos.values():
                self._cancel_pump(repo)

    async def forget(self, workspace_id: UUID, *, purge_cache: bool = False) -> None:
        ws = self._workspaces.pop(workspace_id, None)
        if ws is not None:
            self._drop_repos(ws, ws.repos)
        if purge_cache:
            await asyncio.to_thread(self._store.purge_workspace, workspace_id)

    async def status(self, workspace_id: UUID) -> CodeGraphStatus:
        ws = self._workspaces.get(workspace_id)
        if ws is None:
            return self._disabled(workspace_id)
        probe = await self._refresh(ws)
        return self._compose(ws, probe)

    async def reindex(self, request: CodeReindexRequest) -> CodeReindexResult:
        ws = self._workspaces.get(request.workspace_id)
        current = await self.status(request.workspace_id)
        if ws is None or _refuses_reindex(current):
            return CodeReindexResult(
                accepted=False,
                state=current.state,
                error=current.error
                or make_error(LocalErrorCode.INVALID_REQUEST, "code graph is not configured"),
            )
        unknown = sorted(set(request.repo_names) - set(ws.repos))
        if unknown:
            return CodeReindexResult(
                accepted=False,
                state=current.state,
                error=make_error(
                    LocalErrorCode.INVALID_REQUEST,
                    "reindex names a repository that is not part of the code graph",
                    details={"repo": unknown[0]},
                ),
            )
        names = request.repo_names or list(ws.repos)
        for name in names:
            self._schedule(
                ws, ws.repos[name], 0.0, full=request.mode is CodeReindexMode.FULL_REBUILD
            )
        return CodeReindexResult(
            accepted=True,
            operation_id=f"op-{uuid.uuid4().hex[:16]}",
            state=ComponentState.INDEXING,
        )

    async def on_git_change(self, change: GitChangeLike) -> None:
        for ws in list(self._workspaces.values()):
            if not ws.enabled or ws.invalid is not None:
                continue
            provider = self._provider_of(ws)
            probe = self._probes.get(provider.provider_id) if provider else None
            if provider is None or probe is None or probe[1].state is not ProbeState.AVAILABLE:
                continue
            for repo in list(ws.repos.values()):
                if not same_location(repo.root, Path(change.repo_path)):
                    continue
                if repo.building:
                    repo.rerun = True
                    repo.deadline = self._clock() + self._debounce
                    continue
                await self._check_freshness(ws, repo, provider, probe[1], force=True)
                if repo.stale or repo.snapshot is None:
                    self._schedule(ws, repo, self._debounce, full=False)

    async def search_symbols(self, query: CodeSymbolQuery) -> CodeSymbolResult:
        ws, status = await self._servable(query.workspace_id)
        index_state = _INDEX_STATE[status.state]
        if ws.index is None:
            return CodeSymbolResult(symbols=[], index_state=index_state, complete=False)
        try:
            symbols, cursor = ws.index.search(query.name, query.kinds, query.limit, query.cursor)
        except InvalidCursorError as error:
            raise CodeGraphQueryError(
                make_error(LocalErrorCode.INVALID_REQUEST, "cursor is not valid for this query")
            ) from error
        return CodeSymbolResult(
            symbols=symbols,
            next_cursor=cursor,
            index_state=index_state,
            complete=status.state is ComponentState.READY,
        )

    async def graph_page(self, request: GraphPageRequest) -> GraphPage:
        ws, _ = await self._servable(request.workspace_id, need_data=True)
        assert ws.index is not None
        try:
            return ws.index.page(
                self._source(ws), request.limit, request.cursor, request.node_kinds
            )
        except InvalidCursorError as error:
            raise CodeGraphQueryError(
                make_error(LocalErrorCode.INVALID_REQUEST, "cursor is not valid for this graph")
            ) from error

    async def graph_expand(self, request: GraphExpandRequest) -> GraphPage:
        ws, _ = await self._servable(request.workspace_id, need_data=True)
        assert ws.index is not None
        try:
            return ws.index.expand(
                self._source(ws),
                request.node.node_id,
                request.direction,
                request.relations,
                request.limit,
                request.cursor,
            )
        except (InvalidCursorError, UnknownNodeError) as error:
            raise CodeGraphQueryError(
                make_error(LocalErrorCode.INVALID_REQUEST, "expansion request is not valid")
            ) from error

    def diagnostics(self, workspace_id: UUID) -> list[RepoReport]:
        ws = self._workspaces.get(workspace_id)
        if ws is None:
            return []
        return [
            RepoReport(
                name=repo.name,
                phase=self._phase(repo),
                node_count=len(repo.snapshot.nodes) if repo.snapshot else 0,
                edge_count=len(repo.snapshot.edges) if repo.snapshot else 0,
                failure=repo.failure,
                last_change=repo.last_change,
                dropped=dict(repo.snapshot.dropped) if repo.snapshot else {},
            )
            for repo in ws.repos.values()
        ]

    async def wait_idle(self) -> None:
        while True:
            pumps = [
                repo.pump
                for ws in self._workspaces.values()
                for repo in ws.repos.values()
                if repo.pump is not None and not repo.pump.done()
            ]
            if not pumps:
                return
            await asyncio.gather(*pumps, return_exceptions=True)

    async def close(self) -> None:
        self._closed = True
        pumps: list[asyncio.Task[None]] = []
        for ws in self._workspaces.values():
            for repo in ws.repos.values():
                if repo.pump is not None:
                    pumps.append(repo.pump)
                self._cancel_pump(repo)
        if pumps:
            await asyncio.gather(*pumps, return_exceptions=True)

    async def _servable(
        self, workspace_id: UUID, *, need_data: bool = False
    ) -> tuple[_Workspace, CodeGraphStatus]:
        status = await self.status(workspace_id)
        ws = self._workspaces.get(workspace_id)
        if ws is None or status.state not in _SERVING_STATES:
            raise CodeGraphQueryError(
                status.error
                or make_error(LocalErrorCode.INDEX_ABSENT, "code graph is not available")
            )
        if need_data and ws.index is None:
            raise CodeGraphQueryError(
                make_error(
                    LocalErrorCode.INDEX_ABSENT, "code graph is still being indexed", retryable=True
                )
            )
        return ws, status

    def _provider_of(self, ws: _Workspace) -> CodeGraphProvider | None:
        if ws.config is None or ws.config.code_graph is None:
            return None
        return self._providers.get(ws.config.code_graph.provider_id)

    async def _probe(self, provider: CodeGraphProvider, *, force: bool = False) -> ProviderProbe:
        cached = self._probes.get(provider.provider_id)
        if cached is not None and not force and self._clock() - cached[0] < self._probe_ttl:
            return cached[1]
        probe = await asyncio.to_thread(provider.probe)
        self._probes[provider.provider_id] = (self._clock(), probe)
        return probe

    async def _refresh(self, ws: _Workspace) -> ProviderProbe | None:
        provider = self._provider_of(ws)
        if provider is None or not ws.enabled or ws.invalid is not None:
            return None
        probe = await self._probe(provider)
        if probe.state is ProbeState.AVAILABLE:
            for repo in list(ws.repos.values()):
                await self._check_freshness(ws, repo, provider, probe)
        return probe

    async def _desired_repos(
        self, config: LocalWorkspaceConfig, provider: CodeGraphProvider | None
    ) -> dict[str, _Repo]:
        settings = config.code_graph
        assert settings is not None
        roots = {repo.name: Path(repo.path) for repo in config.roots.repo_roots}
        names = settings.repo_names or list(roots)
        mapping = provider.language_by_extension if provider is not None else {}
        languages = tuple(settings.languages)
        extensions = frozenset(
            ext for ext, language in mapping.items() if not languages or language in languages
        )
        return {
            name: _Repo(
                name=name,
                root=roots[name],
                include=tuple(settings.include_globs),
                exclude=tuple(settings.exclude_globs),
                languages=languages,
                extensions=extensions,
            )
            for name in names
            if name in roots
        }

    async def _load_snapshot(self, ws: _Workspace, repo: _Repo) -> None:
        settings = ws.config.code_graph if ws.config else None
        if settings is None:
            return
        try:
            snapshot = await asyncio.to_thread(
                self._store.load, ws.workspace_id, settings.index.directory_name, repo.name
            )
        except StoreCorruptError:
            repo.corrupt = True
            return
        if snapshot is not None and snapshot.provider_id == settings.provider_id:
            repo.snapshot = snapshot

    async def _check_freshness(
        self,
        ws: _Workspace,
        repo: _Repo,
        provider: CodeGraphProvider,
        probe: ProviderProbe,
        *,
        force: bool = False,
    ) -> None:
        if repo.building or (not force and self._clock() - repo.checked_at < self._freshness_ttl):
            return
        repo.checked_at = self._clock()
        repo.missing = not await asyncio.to_thread(repo.root.is_dir)
        snapshot = repo.snapshot
        if repo.missing or snapshot is None:
            return
        version_changed = snapshot.provider_version != probe.version
        files = None
        if snapshot.content_addressed:
            files = await asyncio.to_thread(
                self._read_files, repo.root, repo.extensions, repo.include, repo.exclude
            )
        if files is None:
            repo.stale = version_changed
            return
        repo.stale = version_changed or files.digest != snapshot.fingerprint
        if repo.stale:
            repo.last_change = summarize_change(snapshot.files, files.files)

    def _schedule(self, ws: _Workspace, repo: _Repo, delay: float, *, full: bool) -> None:
        if self._closed:
            return
        repo.queued = True
        repo.full = repo.full or full
        repo.deadline = self._clock() + delay
        if repo.building:
            repo.rerun = True
            return
        self._cancel_pump(repo)
        repo.pump = asyncio.create_task(self._pump(ws, repo))

    def _cancel_pump(self, repo: _Repo) -> None:
        pump = repo.pump
        if pump is not None and not pump.done():
            pump.cancel()
        repo.pump = None
        repo.queued = False

    def _drop_repos(self, ws: _Workspace, names: Iterable[str]) -> None:
        for name in list(names):
            repo = ws.repos.pop(name, None)
            if repo is not None:
                self._cancel_pump(repo)

    async def _pump(self, ws: _Workspace, repo: _Repo) -> None:
        try:
            while True:
                wait = repo.deadline - self._clock()
                if wait > 0:
                    await asyncio.sleep(wait)
                    continue
                full, repo.full, repo.rerun = repo.full, False, False
                await self._build(ws, repo, full=full)
                if not repo.rerun:
                    return
        finally:
            if repo.pump is asyncio.current_task():
                repo.pump = None
                repo.queued = False

    async def _build(self, ws: _Workspace, repo: _Repo, *, full: bool) -> None:
        provider = self._provider_of(ws)
        settings = ws.config.code_graph if ws.config else None
        if provider is None or settings is None:
            return
        async with self._slots:
            repo.building = True
            try:
                await self._build_locked(ws, repo, provider, settings.index.directory_name, full)
            finally:
                repo.building = False
                repo.checked_at = -math.inf

    async def _build_locked(
        self,
        ws: _Workspace,
        repo: _Repo,
        provider: CodeGraphProvider,
        directory_name: str,
        full: bool,
    ) -> None:
        probe = await self._probe(provider)
        if probe.state is not ProbeState.AVAILABLE:
            return
        if not await asyncio.to_thread(repo.root.is_dir):
            repo.missing = True
            return
        repo.missing = False
        files = await asyncio.to_thread(
            self._read_files, repo.root, repo.extensions, repo.include, repo.exclude
        )
        previous = repo.snapshot
        if (
            not full
            and not repo.corrupt
            and previous is not None
            and files is not None
            and previous.content_addressed
            and files.digest == previous.fingerprint
            and previous.provider_version == probe.version
        ):
            repo.stale, repo.failure = False, None
            return
        source_id = f"code.{provider.provider_id}"
        try:
            if files is not None and not files.files:
                graph = RepoGraph(repo.name, provider.provider_id, probe.version, [], [])
            else:
                graph = await provider.build(
                    BuildRequest(
                        workspace_id=ws.workspace_id,
                        repo_name=repo.name,
                        repo_root=repo.root,
                        work_dir=self._store.work_dir(ws.workspace_id, directory_name, repo.name),
                        include_globs=repo.include,
                        exclude_globs=repo.exclude,
                        languages=repo.languages,
                        full_rebuild=full or repo.corrupt,
                        timeout_seconds=self._timeout,
                    ),
                    source_id,
                )
        except CodeGraphBuildError as error:
            repo.failure = build_failure_error(error, repo.name)
            return
        except Exception:
            logger.exception("code graph provider crashed on repo %s", repo.name)
            repo.failure = make_error(
                LocalErrorCode.INTERNAL_ERROR,
                "code graph provider crashed",
                retryable=True,
                details={"repo": repo.name},
            )
            return
        snapshot = RepoSnapshot(
            repo_name=repo.name,
            provider_id=graph.provider_id,
            provider_version=graph.provider_version,
            built_at=_now(),
            fingerprint=files.digest if files is not None else _opaque_fingerprint(graph),
            content_addressed=files is not None,
            files=files.files if files is not None else {},
            languages=list(graph.languages),
            dropped=graph.dropped,
            nodes=graph.nodes,
            edges=graph.edges,
        )
        try:
            await asyncio.to_thread(self._store.save, ws.workspace_id, directory_name, snapshot)
        except OSError:
            logger.exception("code graph snapshot could not be written for repo %s", repo.name)
            repo.failure = make_error(
                LocalErrorCode.INTERNAL_ERROR,
                "code graph index could not be stored",
                retryable=True,
                details={"repo": repo.name},
            )
            return
        repo.last_change = (
            summarize_change(previous.files, snapshot.files) if previous is not None else None
        )
        repo.snapshot, repo.corrupt, repo.stale, repo.failure = snapshot, False, False, None
        ws.index = self._make_index(ws)

    def _make_index(self, ws: _Workspace) -> CodeGraphIndex | None:
        snapshots = [repo.snapshot for repo in ws.repos.values() if repo.snapshot is not None]
        provider = self._provider_of(ws)
        if not snapshots or provider is None:
            return None
        digest = hashlib.sha256(provider.provider_id.encode())
        for snapshot in sorted(snapshots, key=lambda item: item.repo_name):
            digest.update(f"\n{snapshot.repo_name}\x00{snapshot.fingerprint}".encode())
        return CodeGraphIndex(
            f"code.{provider.provider_id}",
            digest.hexdigest(),
            (node for snapshot in snapshots for node in snapshot.nodes),
            (edge for snapshot in snapshots for edge in snapshot.edges),
        )

    def _source(self, ws: _Workspace) -> GraphSource:
        provider = self._provider_of(ws)
        index = ws.index
        assert provider is not None and index is not None
        built = [repo.snapshot.built_at for repo in ws.repos.values() if repo.snapshot]
        return GraphSource(
            source_id=index.source_id,
            kind=GraphSourceKind.CODE,
            provider_id=provider.provider_id,
            workspace_id=ws.workspace_id,
            generated_at=max(built),
            index_fingerprint=index.fingerprint,
        )

    def _phase(self, repo: _Repo) -> str:
        if repo.missing:
            return "missing"
        if repo.building:
            return "indexing"
        if repo.corrupt:
            return "corrupt"
        if repo.snapshot is None:
            return "failed" if repo.failure is not None else "absent"
        return "stale" if repo.stale or repo.failure is not None else "ready"

    def _disabled(self, workspace_id: UUID) -> CodeGraphStatus:
        return CodeGraphStatus(
            workspace_id=workspace_id,
            state=ComponentState.DISABLED,
            error=make_error(LocalErrorCode.FEATURE_DISABLED, "code graph is disabled"),
        )

    def _compose(self, ws: _Workspace, probe: ProviderProbe | None) -> CodeGraphStatus:
        workspace_id = ws.workspace_id
        if ws.invalid is not None:
            return CodeGraphStatus(
                workspace_id=workspace_id,
                state=ComponentState.UNAVAILABLE,
                error=make_error(ws.invalid, "workspace is not valid, code graph is paused"),
            )
        settings = ws.config.code_graph if ws.config else None
        if not ws.enabled or settings is None:
            return self._disabled(workspace_id)
        provider = self._providers.get(settings.provider_id)
        if provider is None or probe is None:
            return CodeGraphStatus(
                workspace_id=workspace_id,
                state=ComponentState.NOT_INSTALLED,
                error=make_error(
                    LocalErrorCode.PROVIDER_NOT_INSTALLED, "code graph provider is not available"
                ),
            )
        info = ProviderInfo(
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            provider_version=_semver(probe.version),
            capabilities=list(provider.capabilities),
        )
        supported = set(provider.language_by_extension.values())
        unsupported = sorted(set(settings.languages) - supported)
        if probe.state is not ProbeState.AVAILABLE:
            return self._provider_problem(workspace_id, info, probe, unsupported)
        return self._compose_index(ws, info, unsupported)

    def _provider_problem(
        self, workspace_id: UUID, info: ProviderInfo, probe: ProviderProbe, unsupported: list[str]
    ) -> CodeGraphStatus:
        if probe.state is ProbeState.NOT_INSTALLED:
            state, error = (
                ComponentState.NOT_INSTALLED,
                make_error(
                    LocalErrorCode.PROVIDER_NOT_INSTALLED, "code graph provider is not installed"
                ),
            )
        elif probe.state is ProbeState.INCOMPATIBLE:
            state, error = (
                ComponentState.INCOMPATIBLE,
                make_error(
                    LocalErrorCode.PROVIDER_INCOMPATIBLE,
                    probe.reason or "code graph provider version is not supported",
                ),
            )
        else:
            state, error = (
                ComponentState.UNAVAILABLE,
                make_error(
                    LocalErrorCode.INTERNAL_ERROR,
                    probe.reason or "code graph provider is not responding",
                    retryable=True,
                ),
            )
        return CodeGraphStatus(
            workspace_id=workspace_id,
            state=state,
            provider=info,
            unsupported_languages=unsupported,
            error=error,
        )

    def _compose_index(
        self, ws: _Workspace, info: ProviderInfo, unsupported: list[str]
    ) -> CodeGraphStatus:
        workspace_id = ws.workspace_id
        repos = list(ws.repos.values())
        if not repos:
            return CodeGraphStatus(
                workspace_id=workspace_id,
                state=ComponentState.UNAVAILABLE,
                provider=info,
                unsupported_languages=unsupported,
                error=make_error(
                    LocalErrorCode.WORKSPACE_CONFIG_MISSING,
                    "no repository is configured for the code graph",
                ),
            )
        phases = {repo.name: self._phase(repo) for repo in repos}
        languages = sorted(
            {lang for repo in repos if repo.snapshot for lang in repo.snapshot.languages}
        )
        build = partial(
            CodeGraphStatus,
            workspace_id=workspace_id,
            provider=info,
            languages=languages,
            unsupported_languages=unsupported,
        )
        picked = _first_phase(phases, ("missing", "corrupt", "failed"))
        if picked is not None:
            return self._failure_status(ws, build, picked[0], picked[1])
        built = [repo.snapshot for repo in repos if repo.snapshot is not None]
        fingerprint = ws.index.fingerprint if ws.index is not None else None
        items = ws.index.node_count if ws.index is not None else 0
        built_at = min((item.built_at for item in built), default=None)
        if "indexing" in phases.values():
            done = sum(1 for phase in phases.values() if phase in ("ready", "stale"))
            progress = min(99, done * 100 // len(repos))
            index = IndexInfo(
                state=IndexState.INDEXING,
                source_fingerprint=fingerprint,
                item_count=items,
                progress_percent=progress,
            )
            return build(state=ComponentState.INDEXING, index=index)
        if "absent" in phases.values():
            return build(
                state=ComponentState.UNAVAILABLE,
                index=IndexInfo(state=IndexState.ABSENT),
                error=make_error(LocalErrorCode.INDEX_ABSENT, "code graph is not indexed yet"),
            )
        stale = "stale" in phases.values()
        index = IndexInfo(
            state=IndexState.STALE if stale else IndexState.READY,
            built_at=built_at,
            source_fingerprint=fingerprint,
            item_count=items,
        )
        return build(state=ComponentState.STALE if stale else ComponentState.READY, index=index)

    def _failure_status(
        self, ws: _Workspace, build: Callable[..., CodeGraphStatus], name: str, phase: str
    ) -> CodeGraphStatus:
        repo = ws.repos[name]
        details = {"repo": name}
        if phase == "missing":
            state = ComponentState.UNAVAILABLE
            error = make_error(
                LocalErrorCode.WORKSPACE_INACCESSIBLE,
                "a configured repository is missing or unreadable",
                details=details,
            )
        elif phase == "corrupt":
            state = ComponentState.ERROR
            error = make_error(
                LocalErrorCode.INDEX_CORRUPT,
                "the stored code index is unreadable and will be rebuilt",
                retryable=True,
                details=details,
            )
        else:
            state = ComponentState.ERROR
            error = repo.failure or make_error(
                LocalErrorCode.INTERNAL_ERROR, "code graph indexing failed", details=details
            )
        return build(state=state, error=error)


def _refuses_reindex(status: CodeGraphStatus) -> bool:
    if status.state in _REFUSING_STATES:
        return True
    return status.state is ComponentState.UNAVAILABLE and (
        status.error is None or status.error.code is not LocalErrorCode.INDEX_ABSENT
    )


def _first_phase(phases: dict[str, str], order: Sequence[str]) -> tuple[str, str] | None:
    for wanted in order:
        for name, phase in phases.items():
            if phase == wanted:
                return name, phase
    return None


def _opaque_fingerprint(graph: RepoGraph) -> str:
    digest = hashlib.sha256(graph.provider_id.encode())
    for node in graph.nodes:
        digest.update(node.node_id.encode())
    for edge in graph.edges:
        digest.update(edge.edge_id.encode())
    return digest.hexdigest()


_SERVING_STATES = frozenset({ComponentState.READY, ComponentState.STALE, ComponentState.INDEXING})
_REFUSING_STATES = frozenset(
    {
        ComponentState.DISABLED,
        ComponentState.NOT_INSTALLED,
        ComponentState.INCOMPATIBLE,
        ComponentState.PERMISSION_DENIED,
    }
)
_INDEX_STATE: dict[ComponentState, IndexState] = {
    ComponentState.READY: IndexState.READY,
    ComponentState.STALE: IndexState.STALE,
    ComponentState.INDEXING: IndexState.INDEXING,
}
