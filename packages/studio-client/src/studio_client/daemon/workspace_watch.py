"""P4 side of the P5 watch plan: lifecycle of the workspace-driven `GitWatcher`s.

P5 (`studio_workspaces.daemon_watch_plan`) only *describes* what to watch; this
module owns starting, deduplicating, restarting and stopping the watchers. It
never creates a second watcher implementation: every repository is watched by
the existing `GitWatcher`, over the identity-bound outbox of the daemon.

There is deliberately no import of `studio_workspaces` here: the plan is read
through a structural protocol so the two packages stay independent.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

from studio_contracts.local.common import ComponentState
from studio_contracts.local.daemon_control import (
    RuntimeServiceCondition,
    RuntimeServiceHealth,
    RuntimeServiceId,
)

from studio_client.outbox import OutboxStore
from studio_client.watchers import GitChangeListener, GitWatcher, PollingWatcher

_LOGGER = logging.getLogger("studio_client.daemon.workspace_watch")

MAX_WORKSPACE_WATCHERS = 32
"""Below the 64-entry `DaemonHealth.git_watchers` bound, leaving room for the
configured `git_watches`."""


class WatchPlanLike(Protocol):
    @property
    def enabled(self) -> bool: ...

    @property
    def repo_paths(self) -> Sequence[str]: ...


class WorkspaceWatchLike(Protocol):
    @property
    def workspace_id(self) -> UUID: ...

    @property
    def project_id(self) -> UUID: ...

    @property
    def plan(self) -> WatchPlanLike: ...


@dataclass(frozen=True)
class WorkspaceWatch:
    workspace_id: UUID
    project_id: UUID
    plan: WatchPlanLike


class RepoStatus(StrEnum):
    WATCHING = "watching"
    DISABLED = "disabled"
    NOT_A_REPOSITORY = "not_a_repository"
    MISSING = "missing"
    INACCESSIBLE = "inaccessible"
    ALREADY_WATCHED = "already_watched"
    LIMIT_REACHED = "limit_reached"


@dataclass(frozen=True)
class RepoObservation:
    workspace_id: UUID
    repo_path: str
    status: RepoStatus


def probe_repo(path: Path) -> RepoStatus:
    """Filesystem probe; a relative path or any OS error is refused, never guessed."""
    try:
        if not path.is_absolute():
            return RepoStatus.INACCESSIBLE
        if not path.exists():
            return RepoStatus.MISSING
        if not path.is_dir() or not (path / ".git").exists():
            return RepoStatus.NOT_A_REPOSITORY
    except OSError:
        return RepoStatus.INACCESSIBLE
    return RepoStatus.WATCHING


WatcherFactory = Callable[[Path, UUID], PollingWatcher]


@dataclass
class _Running:
    watcher: PollingWatcher
    task: asyncio.Task[None]
    workspace_id: UUID


def path_identity(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _instance_key(path: Path) -> str:
    return "ws-" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


class WorkspaceWatchSet:
    def __init__(
        self,
        *,
        machine_id: UUID,
        outbox: OutboxStore,
        interval_seconds: float = 30.0,
        watcher_factory: WatcherFactory | None = None,
        probe: Callable[[Path], RepoStatus] = probe_repo,
        reserved: Collection[Path] = (),
        change_listener: GitChangeListener | None = None,
    ) -> None:
        self._change_listener = change_listener
        self._machine_id = machine_id
        self._outbox = outbox
        self._interval_seconds = interval_seconds
        self._factory = watcher_factory or self._default_factory
        self._probe = probe
        self._reserved = frozenset(path_identity(path) for path in reserved)
        self._lock = threading.Lock()
        self._running: dict[Path, _Running] = {}
        self._observations: list[RepoObservation] = []

    def _default_factory(self, repo_path: Path, project_id: UUID) -> PollingWatcher:
        return GitWatcher(
            repo_path=repo_path,
            project_id=project_id,
            machine_id=self._machine_id,
            outbox=self._outbox,
            interval_seconds=self._interval_seconds,
            on_change=self._change_listener,
        )

    @property
    def watched_paths(self) -> list[Path]:
        with self._lock:
            return sorted(self._running)

    @property
    def observations(self) -> list[RepoObservation]:
        return list(self._observations)

    async def reconcile(self, workspaces: Sequence[WorkspaceWatchLike]) -> list[RepoObservation]:
        """Make the running watchers match the plans; idempotent."""
        desired: dict[Path, tuple[UUID, UUID]] = {}
        observations: list[RepoObservation] = []
        for workspace in sorted(workspaces, key=lambda item: str(item.workspace_id)):
            if not workspace.plan.enabled:
                observations.append(
                    RepoObservation(workspace.workspace_id, "", RepoStatus.DISABLED)
                )
                continue
            for raw in workspace.plan.repo_paths:
                path = Path(raw)
                status = await asyncio.to_thread(self._probe, path)
                if status is RepoStatus.WATCHING:
                    if path_identity(path) in self._reserved or any(
                        path_identity(path) == path_identity(known) for known in desired
                    ):
                        status = RepoStatus.ALREADY_WATCHED
                    elif len(desired) >= MAX_WORKSPACE_WATCHERS:
                        status = RepoStatus.LIMIT_REACHED
                    else:
                        desired[path] = (workspace.workspace_id, workspace.project_id)
                observations.append(RepoObservation(workspace.workspace_id, raw, status))
        with self._lock:
            known_paths = list(self._running)
        for path in [known for known in known_paths if known not in desired]:
            await self._stop_one(path)
        for path, (workspace_id, project_id) in desired.items():
            with self._lock:
                current = self._running.get(path)
            if current is not None and not current.task.done():
                continue
            if current is not None:
                await self._stop_one(path)
            watcher = self._factory(path, project_id)
            task = asyncio.create_task(watcher.run(), name=f"git-watch-{_instance_key(path)}")
            with self._lock:
                self._running[path] = _Running(watcher, task, workspace_id)
        self._observations = observations
        return list(observations)

    async def _stop_one(self, path: Path) -> None:
        with self._lock:
            running = self._running.pop(path, None)
        if running is None:
            return
        running.watcher.request_stop()
        results = await asyncio.gather(running.task, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                _LOGGER.warning("workspace git watcher ended with an error", exc_info=result)

    def request_stop(self) -> None:
        with self._lock:
            runners = list(self._running.values())
        for running in runners:
            running.watcher.request_stop()

    async def stop(self) -> None:
        for path in self.watched_paths:
            await self._stop_one(path)
        self._observations = []

    def health(self) -> list[RuntimeServiceHealth]:
        entries: list[RuntimeServiceHealth] = []
        with self._lock:
            snapshot = sorted(self._running.items())
        for path, running in snapshot:
            alive = not running.task.done()
            entries.append(
                RuntimeServiceHealth(
                    service=RuntimeServiceId.GIT_WATCHER,
                    instance_key=_instance_key(path),
                    state=ComponentState.READY if alive else ComponentState.UNAVAILABLE,
                    condition=(
                        RuntimeServiceCondition.HEALTHY
                        if alive
                        else RuntimeServiceCondition.OFFLINE
                    ),
                )
            )
        return entries
