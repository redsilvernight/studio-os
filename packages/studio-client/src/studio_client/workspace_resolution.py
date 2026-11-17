from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx
from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import LocalWorkspaceConfig
from studio_contracts.projects import ResolveRepositoryResponse
from studio_contracts.repositories import normalize_remote_url
from studio_workspaces import (
    DetectedRepository,
    GitRepoInfo,
    GitStatus,
    RootConfirmationService,
    WorkspaceStore,
    WorkspaceStoreError,
    detect_git,
    forget_detected_repository,
    main_repo_root,
    record_detected_repository,
    register_workspace,
)
from studio_workspaces.path_safety import workspace_binding_key

from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig, default_config_path
from studio_client.errors import ConflictError, StudioApiError, TransportError

MAX_REMOTES = 10


class ResolutionReason(StrEnum):
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    NO_GIT_REMOTE = "no_git_remote"
    NOT_A_REPO = "not_a_repo"
    GIT_UNAVAILABLE = "git_unavailable"
    INACCESSIBLE = "inaccessible"
    SERVER_UNREACHABLE = "server_unreachable"
    SERVER_ERROR = "server_error"
    OTHER_PROFILE = "other_profile"
    INVALID_RESPONSE = "invalid_response"
    WORKSPACE_ERROR = "workspace_error"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class WorkspaceResolution:
    """The workspace of one folder, whether it came from the machine-local
    registry (cache) or from the server's repository resolution. `reason` is
    the machine-readable outcome; `detected` carries an unresolved repository
    that P3-detected can offer to link."""

    status: ResolutionStatus
    reason: ResolutionReason
    path: str
    repo_root: str | None = None
    repository_key: str | None = None
    remotes: tuple[str, ...] = ()
    project_id: UUID | None = None
    project_slug: str | None = None
    workspace: LocalWorkspaceConfig | None = None
    created: bool = False
    cached: bool = False
    detected: DetectedRepository | None = None
    detail: str = ""

    @property
    def resolved(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED

    @property
    def workspace_id(self) -> UUID | None:
        return self.workspace.workspace_id if self.workspace is not None else None


class RepositoryResolver(Protocol):
    async def resolve_repository(self, remotes: Sequence[str]) -> ResolveRepositoryResponse: ...


class ResolverFactory(Protocol):
    def __call__(self, profile: ProfileRef) -> AbstractAsyncContextManager[RepositoryResolver]: ...


@dataclass(frozen=True)
class _LocalState:
    path: str
    root: str | None
    remotes: tuple[str, ...]
    repository_key: str | None
    workspace: LocalWorkspaceConfig | None = None
    failure: WorkspaceResolution | None = None


@dataclass(frozen=True)
class _ServerOutcome:
    response: ResolveRepositoryResponse | None = None
    reason: ResolutionReason | None = None
    detail: str = ""


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _absolute(path: str | Path) -> str:
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(path))))


def normalize_remotes(remotes: Sequence[str]) -> tuple[str, ...]:
    """Normalised fetch URLs, invalid ones skipped, in declaration order."""
    normalized: list[str] = []
    for remote in remotes:
        try:
            key = normalize_remote_url(remote)
        except ValueError:
            continue
        if key not in normalized:
            normalized.append(key)
    return tuple(normalized)


def _config_paths(config: LocalWorkspaceConfig) -> list[str]:
    return [config.roots.workspace_root, *(repo.path for repo in config.roots.repo_roots)]


def _matching(
    configs: Sequence[LocalWorkspaceConfig], roots: Sequence[str | None]
) -> LocalWorkspaceConfig | None:
    wanted = {workspace_binding_key(root) for root in roots if root}
    if not wanted:
        return None
    for config in configs:
        if any(workspace_binding_key(path) in wanted for path in _config_paths(config)):
            return config
    return None


def _failure(
    path: str,
    reason: ResolutionReason,
    *,
    root: str | None = None,
    repository_key: str | None = None,
    remotes: Sequence[str] = (),
    detail: str = "",
) -> WorkspaceResolution:
    return WorkspaceResolution(
        status=ResolutionStatus.UNRESOLVED,
        reason=reason,
        path=path,
        repo_root=root,
        repository_key=repository_key,
        remotes=tuple(remotes),
        detail=detail,
    )


def _resolved(
    path: str,
    workspace: LocalWorkspaceConfig,
    *,
    root: str | None,
    repository_key: str | None,
    remotes: Sequence[str],
    created: bool,
    cached: bool,
) -> WorkspaceResolution:
    return WorkspaceResolution(
        status=ResolutionStatus.RESOLVED,
        reason=ResolutionReason.RESOLVED,
        path=path,
        repo_root=root,
        repository_key=repository_key,
        remotes=tuple(remotes),
        project_id=workspace.project_id,
        project_slug=workspace.project_slug,
        workspace=workspace,
        created=created,
        cached=cached,
    )


def _probe_local(
    path: str | Path,
    profile: ProfileRef,
    store: WorkspaceStore,
    probe: Callable[[str], GitRepoInfo],
) -> _LocalState:
    absolute = _absolute(path)
    try:
        readable = os.path.isdir(absolute) and os.access(absolute, os.R_OK | os.X_OK)
    except OSError:
        readable = False
    if not readable:
        return _LocalState(
            absolute,
            None,
            (),
            None,
            failure=_failure(
                absolute,
                ResolutionReason.INACCESSIBLE,
                detail="path is not readable",
            ),
        )

    mine = store.list_workspaces(profile)
    everyone = store.all_workspaces()

    cached = _matching(mine, [absolute])
    if cached is not None:
        return _LocalState(
            absolute,
            cached.roots.workspace_root,
            (),
            None,
            workspace=cached,
        )

    foreign = _matching([config for config in everyone if config.profile != profile], [absolute])
    if foreign is not None:
        return _LocalState(
            absolute,
            foreign.roots.workspace_root,
            (),
            None,
            failure=_failure(
                absolute,
                ResolutionReason.OTHER_PROFILE,
                root=foreign.roots.workspace_root,
                detail="this folder belongs to another server origin",
            ),
        )

    info = probe(absolute)
    if info.status is not GitStatus.VALID:
        reason = (
            ResolutionReason.NOT_A_REPO
            if info.status is GitStatus.NOT_A_REPO
            else ResolutionReason.GIT_UNAVAILABLE
            if info.status in (GitStatus.GIT_ABSENT, GitStatus.INVALID_REPO)
            else ResolutionReason.INACCESSIBLE
        )
        return _LocalState(
            absolute,
            None,
            (),
            None,
            failure=_failure(absolute, reason, detail=str(info.status.value)),
        )

    root = main_repo_root(info) or info.repo_root or absolute
    raw_remotes = info.remotes or ((info.remote,) if info.remote else ())
    remotes = normalize_remotes(raw_remotes)
    repository_key = remotes[0] if remotes else None
    roots = [root, info.repo_root, absolute]

    cached = _matching(mine, roots)
    if cached is not None:
        return _LocalState(
            absolute,
            root,
            remotes,
            repository_key,
            workspace=cached,
        )

    foreign = _matching([config for config in everyone if config.profile != profile], roots)
    if foreign is not None:
        return _LocalState(
            absolute,
            root,
            remotes,
            repository_key,
            failure=_failure(
                absolute,
                ResolutionReason.OTHER_PROFILE,
                root=root,
                repository_key=repository_key,
                remotes=remotes,
                detail="this repository belongs to another server origin",
            ),
        )

    if not remotes:
        return _LocalState(
            absolute,
            root,
            (),
            None,
            failure=_failure(
                absolute,
                ResolutionReason.NO_GIT_REMOTE,
                root=root,
                detail="no fetch remote to identify the repository",
            ),
        )

    return _LocalState(absolute, root, remotes, repository_key)


def _create_workspace(
    registry_dir: Path,
    profile: ProfileRef,
    project_id: UUID,
    root: str,
    project_slug: str | None,
) -> LocalWorkspaceConfig:
    return register_workspace(
        registry_dir,
        profile,
        project_id,
        root,
        project_slug=project_slug,
    ).config


async def _call_server(resolver: RepositoryResolver, remotes: Sequence[str]) -> _ServerOutcome:
    try:
        response = await resolver.resolve_repository(list(remotes[:MAX_REMOTES]))
    except ConflictError as exc:
        if exc.error_code == "ambiguous":
            return _ServerOutcome(reason=ResolutionReason.AMBIGUOUS, detail=exc.message)
        return _ServerOutcome(reason=ResolutionReason.SERVER_ERROR, detail=str(exc))
    except TransportError as exc:
        return _ServerOutcome(reason=ResolutionReason.SERVER_UNREACHABLE, detail=str(exc))
    except httpx.TransportError as exc:
        return _ServerOutcome(reason=ResolutionReason.SERVER_UNREACHABLE, detail=str(exc))
    except StudioApiError as exc:
        return _ServerOutcome(reason=ResolutionReason.SERVER_ERROR, detail=str(exc))
    return _ServerOutcome(response=response)


def _default_resolver(profile: ProfileRef) -> AbstractAsyncContextManager[RepositoryResolver]:
    return StudioApiClient(
        ClientConfig(
            api_base_url=str(profile.server_origin),
            profile_id=profile.profile_id,
        )
    )


async def _resolve_on_server(
    profile: ProfileRef,
    remotes: Sequence[str],
    client: RepositoryResolver | None,
    factory: ResolverFactory | None,
) -> _ServerOutcome:
    if client is not None:
        return await _call_server(client, remotes)
    async with (factory or _default_resolver)(profile) as resolver:
        return await _call_server(resolver, remotes)


def _record_detected(
    registry_dir: Path,
    profile: ProfileRef,
    root: str | None,
    remotes: Sequence[str],
    repository_key: str | None,
    reason: ResolutionReason,
    now: Callable[[], datetime],
) -> DetectedRepository | None:
    if root is None or not remotes:
        return None
    return record_detected_repository(
        registry_dir,
        profile,
        root,
        remotes,
        repository_key,
        reason.value,
        now=now,
    )


async def resolve_workspace(
    path: str | Path,
    profile: ProfileRef,
    *,
    registry_dir: Path | None = None,
    store: WorkspaceStore | None = None,
    client: RepositoryResolver | None = None,
    client_factory: ResolverFactory | None = None,
    probe: Callable[[str], GitRepoInfo] | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> WorkspaceResolution:
    """The workspace of `path`, created when the server of `profile` recognises
    one of its Git remotes. A folder already covered by the machine-local
    registry (main checkout or any of its worktrees) answers from the cache
    without touching the network; every failure is a typed `unresolved`
    result and never writes a workspace config."""
    registry = Path(registry_dir) if registry_dir is not None else default_config_path().parent
    workspace_store = store or WorkspaceStore(registry, RootConfirmationService())

    local = await asyncio.to_thread(
        _probe_local, path, profile, workspace_store, probe or detect_git
    )
    if local.workspace is not None:
        return _resolved(
            local.path,
            local.workspace,
            root=local.root,
            repository_key=local.repository_key,
            remotes=local.remotes,
            created=False,
            cached=True,
        )
    if local.failure is not None:
        return local.failure

    outcome = await _resolve_on_server(profile, local.remotes, client, client_factory)
    if outcome.response is not None and outcome.response.status == "resolved":
        project_id = outcome.response.project_id
        if project_id is None:
            failure = _failure(
                local.path,
                ResolutionReason.INVALID_RESPONSE,
                root=local.root,
                repository_key=local.repository_key,
                remotes=local.remotes,
                detail="resolved response carries no project_id",
            )
        else:
            try:
                config = await asyncio.to_thread(
                    _create_workspace,
                    registry,
                    profile,
                    project_id,
                    local.root or local.path,
                    outcome.response.slug,
                )
            except WorkspaceStoreError as exc:
                failure = _failure(
                    local.path,
                    ResolutionReason.OTHER_PROFILE
                    if "another project or profile" in str(exc)
                    else ResolutionReason.WORKSPACE_ERROR,
                    root=local.root,
                    repository_key=local.repository_key,
                    remotes=local.remotes,
                    detail=str(exc),
                )
            else:
                try:
                    await asyncio.to_thread(
                        forget_detected_repository, registry, profile, config.roots.workspace_root
                    )
                except OSError:
                    pass
                return _resolved(
                    local.path,
                    config,
                    root=local.root,
                    repository_key=local.repository_key,
                    remotes=local.remotes,
                    created=True,
                    cached=False,
                )
    elif outcome.response is not None:
        failure = _failure(
            local.path,
            ResolutionReason.NOT_FOUND,
            root=local.root,
            repository_key=local.repository_key,
            remotes=local.remotes,
            detail="no project matches these remotes",
        )
    else:
        failure = _failure(
            local.path,
            outcome.reason or ResolutionReason.SERVER_ERROR,
            root=local.root,
            repository_key=local.repository_key,
            remotes=local.remotes,
            detail=outcome.detail,
        )

    detected: DetectedRepository | None = None
    try:
        detected = await asyncio.to_thread(
            _record_detected,
            registry,
            profile,
            local.root,
            local.remotes,
            local.repository_key,
            failure.reason,
            now,
        )
    except OSError as exc:
        failure = replace(
            failure,
            detail=f"{failure.detail} (detected repository not recorded: {exc})".strip(),
        )
    return replace(failure, detected=detected)


def resolve_workspace_sync(
    path: str | Path,
    profile: ProfileRef,
    *,
    registry_dir: Path | None = None,
    store: WorkspaceStore | None = None,
    client: RepositoryResolver | None = None,
    client_factory: ResolverFactory | None = None,
    probe: Callable[[str], GitRepoInfo] | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> WorkspaceResolution:
    """Synchronous wrapper for CLI and bootstrap callers."""
    coroutine = resolve_workspace(
        path,
        profile,
        registry_dir=registry_dir,
        store=store,
        client=client,
        client_factory=client_factory,
        probe=probe,
        now=now,
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()
