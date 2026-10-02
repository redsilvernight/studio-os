from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import BinaryIO
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from studio_contracts.local.common import ComponentId, ComponentState, LocalError, LocalErrorCode
from studio_contracts.local.daemon_control import (
    DaemonHealth,
    DaemonInstanceRef,
    DaemonOwnership,
    DaemonRunState,
    DaemonStatus,
    OutboxSummary,
    RuntimeServiceCondition,
    RuntimeServiceHealth,
    RuntimeServiceId,
    instance_lock_key,
)
from studio_contracts.local.handshake import ProtocolVersion
from studio_contracts.local.identity import IdentityBinding, ProfileRef, partition_key
from studio_contracts.task_launch import TaskLaunch

from studio_client.api_client import StudioApiClient
from studio_client.capabilities import build_capabilities, neutral_context
from studio_client.config import ClientConfig, GitWatchConfig, default_config_path
from studio_client.daemon.heartbeat import HeartbeatDaemon, build_godot_watchers
from studio_client.daemon.launch_executor import LaunchExecutor, ResolvedLaunch
from studio_client.daemon.launch_policy import build_launch_policy
from studio_client.daemon.launch_prepare import LaunchPreparer
from studio_client.daemon.launch_puller import LaunchPuller
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.daemon.launch_runner import LaunchRunner
from studio_client.daemon.launch_settings_bridge import effective_launch_config
from studio_client.daemon.workspace_watch import (
    RepoObservation,
    WorkspaceWatchLike,
    WorkspaceWatchSet,
)
from studio_client.errors import (
    AuthenticationError,
    ServerError,
    StudioApiError,
    TransportError,
)
from studio_client.harness.registry import HarnessRegistry
from studio_client.outbox import (
    OutboxIdentityError,
    OutboxReplayer,
    OutboxStore,
    connect,
    connect_read_only,
    default_outbox_path,
    partitioned_outbox_path,
)
from studio_client.outbox.legacy import LegacyOutboxError, inspect_legacy_outbox
from studio_client.retry import RetryPolicy
from studio_client.watchers import GitChangeListener, PollingWatcher

_LOGGER = logging.getLogger("studio_client.daemon.runtime")

WorkspaceSource = Callable[[ProfileRef], Sequence[WorkspaceWatchLike]]
WorkspaceRefreshListener = Callable[[], Awaitable[None]]
GitWatchSource = Callable[[], Sequence[GitWatchConfig]]
DEFAULT_WORKSPACE_SYNC_SECONDS = 15.0


class AlreadyRunningError(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: BinaryIO | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def release(self) -> None:
        handle = self._file
        if handle is None:
            return
        try:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._file = None

    def __enter__(self) -> InstanceLock:
        if not self.acquire():
            raise AlreadyRunningError("a daemon is already running for this profile")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


def server_origin(api_base_url: str) -> str:
    parsed = urlsplit(api_base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("api_base_url must be an absolute HTTP(S) URL")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _launch_secrets() -> tuple[str, ...]:
    """Literal secrets a launched harness could echo in its output. The machine
    token lives in the environment only in headless/CI runs; the harness's own
    MCP credential is masked by `redact_text`'s `Bearer` rule."""
    token = os.environ.get("STUDIO_CLIENT_MACHINE_TOKEN")
    return (token,) if token else ()


def build_launch_resolver(
    client: StudioApiClient,
    registry: HarnessRegistry,
    config: ClientConfig,
    *,
    workspace_repo: Callable[[UUID], Path | None] | None = None,
) -> Callable[[TaskLaunch], Awaitable[ResolvedLaunch | None]]:
    """Resolves a launch to the repository, task title, adapter and probing
    context. The repository comes from `git_watches`, else from a registered
    workspace (`workspace_repo`). `None` means the launch cannot be prepared
    locally (no known repository, or unknown harness)."""

    async def resolve(launch: TaskLaunch) -> ResolvedLaunch | None:
        repo_root = config.git_repo_for_project(launch.project_id)
        if repo_root is None and workspace_repo is not None:
            repo_root = workspace_repo(launch.project_id)
        if repo_root is None:
            _LOGGER.warning(
                "launch cannot be prepared: no repository for project %s", launch.project_id
            )
            return None
        adapter = registry.get(launch.harness_id)
        if adapter is None:
            _LOGGER.warning("launch cannot be prepared: unknown harness %s", launch.harness_id)
            return None
        title: str | None = None
        try:
            title = (await client.get_task(launch.task_id)).title
        except StudioApiError:
            _LOGGER.warning("launch task title unavailable; using a generic slug", exc_info=True)
        return ResolvedLaunch(
            repo_root=repo_root,
            task_title=title,
            adapter=adapter,
            ctx=neutral_context(config),
        )

    return resolve


class DaemonRuntime:
    def __init__(
        self,
        config: ClientConfig,
        *,
        agent_id: UUID | None = None,
        data_root: Path | None = None,
        ownership: DaemonOwnership = DaemonOwnership.EXTERNAL,
        workspace_source: WorkspaceSource | None = None,
        workspace_sync_seconds: float = DEFAULT_WORKSPACE_SYNC_SECONDS,
        git_change_listener: GitChangeListener | None = None,
        workspace_refresh_listener: WorkspaceRefreshListener | None = None,
        git_watch_source: GitWatchSource | None = None,
    ) -> None:
        self._git_watch_source = git_watch_source
        self._git_change_listener = git_change_listener
        self._workspace_refresh_listener = workspace_refresh_listener
        if config.machine_id is None:
            raise ValueError("ClientConfig.machine_id must be set to run the daemon")
        self.config = config
        self.agent_id = agent_id
        self.profile = ProfileRef(
            profile_id=config.profile_id,
            server_origin=server_origin(config.api_base_url),
        )
        self.binding = IdentityBinding(
            server_origin=self.profile.server_origin,
            profile_id=self.profile.profile_id,
            machine_id=config.machine_id,
        )
        self.data_root = data_root or default_config_path().parent
        self.outbox_path = partitioned_outbox_path(self.binding, root=self.data_root / "outbox")
        self._legacy_outbox_path = default_outbox_path()
        self._lock = InstanceLock(
            self.data_root / "locks" / f"{instance_lock_key(self.profile)}.lock"
        )
        self._ownership = ownership
        self._instance_id = uuid4()
        self._started_at: datetime | None = None
        self._store: OutboxStore | None = None
        self._heartbeat: HeartbeatDaemon | None = None
        self._replayer: OutboxReplayer | None = None
        self._launch_executor: LaunchExecutor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._watchers: list[PollingWatcher] = []
        self._workspace_watches: WorkspaceWatchSet | None = None
        self._workspace_inputs: list[WorkspaceWatchLike] = []
        self._git_watch_inputs: list[GitWatchConfig] = list(config.git_watches)
        self._workspace_source = workspace_source
        self._workspace_sync_seconds = workspace_sync_seconds
        self._stop_event: asyncio.Event | None = None
        self._stop_requested = False

    def request_stop(
        self,
        *,
        drain_outbox: bool = False,
        timeout_seconds: float = 0,
    ) -> bool:
        drained = True
        if drain_outbox and self._loop is not None and self._replayer is not None:
            future = asyncio.run_coroutine_threadsafe(self._replayer.replay_ready(), self._loop)
            try:
                future.result(timeout=max(timeout_seconds, 0.1))
            except Exception:  # noqa: BLE001
                future.cancel()
                drained = False
                _LOGGER.warning("outbox drain did not complete before daemon shutdown")
        self._stop_requested = True
        loop = self._loop
        try:
            on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if loop is not None and not on_loop:
            try:
                loop.call_soon_threadsafe(self._signal_stop)
                return drained
            except RuntimeError:
                pass
        self._signal_stop()
        return drained

    def _signal_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._heartbeat is not None:
            self._heartbeat.request_stop()
        for watcher in self._watchers:
            watcher.request_stop()
        if self._workspace_watches is not None:
            self._workspace_watches.request_stop()

    async def reconcile_workspace_watchers(
        self, workspaces: Sequence[WorkspaceWatchLike] | None = None
    ) -> list[RepoObservation]:
        """Apply the P5 watch plans through the P4 watcher lifecycle. Before the
        daemon runs, the plans are only remembered and applied at startup."""
        if workspaces is not None:
            self._workspace_inputs = list(workspaces)
        watches = self._workspace_watches
        if watches is None or self._stop_requested:
            return []
        return await watches.reconcile(self._workspace_inputs, self._git_watch_inputs)

    async def refresh_workspace_watchers(self) -> list[RepoObservation]:
        """Re-read the configured `git_watches` and the workspace plans, then
        reconcile; an unreadable source keeps its previous inputs."""
        if self._git_watch_source is not None:
            try:
                self._git_watch_inputs = list(await asyncio.to_thread(self._git_watch_source))
            except Exception:  # noqa: BLE001
                _LOGGER.warning("git_watches unreadable; keeping current watchers", exc_info=True)
        source = self._workspace_source
        if source is not None:
            try:
                workspaces = await asyncio.to_thread(source, self.profile)
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "workspace source unreadable; keeping current watchers", exc_info=True
                )
            else:
                if self._workspace_refresh_listener is not None:
                    try:
                        await self._workspace_refresh_listener()
                    except Exception:  # noqa: BLE001
                        _LOGGER.warning("workspace refresh listener failed", exc_info=True)
                self._workspace_inputs = list(workspaces)
        return await self.reconcile_workspace_watchers()

    def _workspace_project_ids(self) -> tuple[UUID, ...]:
        """Project IDs registered as Desktop workspaces. A workspace is a local
        project registration, so it feeds both the capability report and the
        local launch gate — not only the watchers."""
        return tuple(watch.project_id for watch in self._workspace_inputs)

    def _workspace_repo_for(self, project_id: UUID) -> Path | None:
        """First repository declared by a workspace of `project_id`, if any. A
        workspace is a project registration, so its repository is a valid launch
        root, just like a `git_watches` entry."""
        for watch in self._workspace_inputs:
            if watch.project_id != project_id:
                continue
            paths = watch.plan.repo_paths
            if paths:
                return Path(paths[0])
        return None

    async def _workspace_sync_loop(self) -> None:
        stop = self._stop_event
        if stop is None or (self._workspace_source is None and self._git_watch_source is None):
            return
        while not self._stop_requested:
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._workspace_sync_seconds)
            except TimeoutError:
                await self.refresh_workspace_watchers()

    async def run(self) -> None:
        if not self._lock.acquire():
            raise AlreadyRunningError("a daemon is already running for this profile")
        try:
            self._loop = asyncio.get_running_loop()
            self._stop_event = asyncio.Event()
            self._guard_legacy_outbox()
            store = OutboxStore(connect(self.outbox_path))
            store.bind_identity(self.binding)
            self._store = store
            self._started_at = datetime.now(UTC)
            async with StudioApiClient(self.config) as client:
                policy = RetryPolicy(
                    self.config.max_attempts,
                    self.config.backoff_initial,
                    self.config.backoff_max,
                )
                replayer = OutboxReplayer(store, client, policy, active_binding=self.binding)
                self._replayer = replayer
                registry = HarnessRegistry()
                reporter = LaunchReporter(store)
                executor = LaunchExecutor(
                    client=client,
                    reporter=reporter,
                    preparer=LaunchPreparer(),
                    runner=LaunchRunner(),
                    resolve=build_launch_resolver(
                        client,
                        registry,
                        self.config,
                        workspace_repo=self._workspace_repo_for,
                    ),
                    timeout_seconds=self.config.launch_timeout_seconds,
                    poll_seconds=self.config.launch_status_poll_seconds,
                    secrets=_launch_secrets(),
                    models=self.config.launch_models,
                )
                self._launch_executor = executor
                executor.start()
                self._heartbeat = HeartbeatDaemon(
                    client,
                    self.config,
                    agent_id=self.agent_id,
                    replayer=replayer,
                    capabilities_provider=lambda: build_capabilities(
                        effective_launch_config(self.config, self.data_root),
                        registry=registry,
                        running_launches=executor.running,
                        extra_project_ids=self._workspace_project_ids(),
                    ),
                    launch_puller=LaunchPuller(
                        client,
                        self.binding.machine_id,
                        lambda: build_launch_policy(
                            effective_launch_config(self.config, self.data_root),
                            registry=registry,
                            extra_project_ids=self._workspace_project_ids(),
                        ),
                        reporter,
                    ),
                    launch_executor=executor,
                )
                self._watchers = build_godot_watchers(self.config, store)
                self._workspace_watches = WorkspaceWatchSet(
                    machine_id=self.binding.machine_id,
                    outbox=store,
                    interval_seconds=self.config.git_watch_interval_seconds,
                    change_listener=self._git_change_listener,
                )
                if not self._stop_requested:
                    await self.refresh_workspace_watchers()
                if self._stop_requested:
                    self.request_stop()
                await asyncio.gather(
                    self._heartbeat.run(),
                    self._workspace_sync_loop(),
                    *(watcher.run() for watcher in self._watchers),
                )
        finally:
            self.request_stop()
            if self._workspace_watches is not None:
                await self._workspace_watches.stop()
                self._workspace_watches = None
            if self._launch_executor is not None:
                await self._launch_executor.aclose()
                self._launch_executor = None
            if self._store is not None:
                self._store.connection.close()
            self._store = None
            self._replayer = None
            self._stop_event = None
            self._loop = None
            self._lock.release()

    def health(self) -> DaemonHealth:
        now = datetime.now(UTC)
        store = self._store
        heartbeat = self._heartbeat
        status = DaemonStatus(state=DaemonRunState.STOPPED)
        outbox_summary: OutboxSummary | None = None
        denied_count = 0
        denied_projects: list[str] = []
        if store is not None and self._started_at is not None:
            started_at = self._started_at
            reader = OutboxStore(connect_read_only(self.outbox_path))
            try:
                pending_count = reader.pending_count()
                oldest_pending_at = reader.oldest_pending_at()
                denied_count, denied_projects = reader.project_access_denied_since(started_at)
            finally:
                reader.connection.close()
            outbox_summary = OutboxSummary(
                binding=self.binding,
                partition_key=partition_key(self.binding),
                pending_count=pending_count,
                oldest_pending_at=oldest_pending_at,
            )
            status = DaemonStatus(
                state=DaemonRunState.RUNNING,
                instance=DaemonInstanceRef(
                    instance_id=self._instance_id,
                    profile=self.profile,
                    lock_key=instance_lock_key(self.profile),
                    pid=os.getpid(),
                    ownership=self._ownership,
                    daemon_version="0.1.0",
                    started_at=started_at,
                ),
                negotiated=ProtocolVersion(major=1, minor=0),
                outbox=outbox_summary,
            )
        heartbeat_health = self._heartbeat_health(heartbeat)
        watcher_health = [
            RuntimeServiceHealth(
                service=RuntimeServiceId.GIT_WATCHER,
                instance_key=f"watch-{index + 1:02d}",
                state=ComponentState.READY,
                condition=RuntimeServiceCondition.HEALTHY,
            )
            for index, _ in enumerate(self._watchers)
        ]
        if self._workspace_watches is not None:
            watcher_health.extend(self._workspace_watches.health())
        watcher_health = watcher_health[:64]
        replay_condition = RuntimeServiceCondition.DISABLED
        replay_state = ComponentState.DISABLED
        replay_error: LocalError | None = None
        if heartbeat is not None and heartbeat.last_replay is not None:
            replay_state = ComponentState.READY
            replay_condition = RuntimeServiceCondition.HEALTHY
            if heartbeat.last_replay.identity_mismatch:
                replay_state = ComponentState.ERROR
                replay_condition = RuntimeServiceCondition.ERROR
                replay_error = LocalError(
                    code=LocalErrorCode.IDENTITY_MISMATCH,
                    message="Queued work belongs to a different identity.",
                    component=ComponentId.DAEMON,
                    retryable=False,
                )
        if replay_error is None and denied_count > 0:
            # Project isolation refused queued work (403, final): the rows sit
            # in `dead_letter`, never retried — say so instead of "healthy".
            replay_state = ComponentState.PERMISSION_DENIED
            replay_condition = RuntimeServiceCondition.ERROR
            replay_error = LocalError(
                code=LocalErrorCode.PERMISSION_DENIED,
                message=(
                    "Queued work was refused: this account has no access to the project. "
                    "The entries were moved to the dead-letter queue and will not be retried."
                ),
                component=ComponentId.DAEMON,
                retryable=False,
                details={
                    "dead_letters": denied_count,
                    "project_ids": ",".join(denied_projects)[:256],
                },
            )
        return DaemonHealth(
            observed_at=now,
            status=status,
            heartbeat=heartbeat_health,
            git_watchers=watcher_health,
            outbox_replay=RuntimeServiceHealth(
                service=RuntimeServiceId.OUTBOX_REPLAY,
                state=replay_state,
                condition=replay_condition,
                last_attempt_at=(heartbeat.last_success_at if heartbeat else None),
                last_success_at=(heartbeat.last_success_at if heartbeat else None),
                error=replay_error,
            ),
            providers=[],
        )

    def _guard_legacy_outbox(self) -> None:
        if self._legacy_outbox_path == self.outbox_path or not self._legacy_outbox_path.exists():
            return
        try:
            report = inspect_legacy_outbox(self._legacy_outbox_path)
        except LegacyOutboxError as exc:
            raise OutboxIdentityError(["binding_missing"]) from exc
        if report.has_queued_work:
            raise OutboxIdentityError(["binding_missing"])

    @staticmethod
    def _heartbeat_health(heartbeat: HeartbeatDaemon | None) -> RuntimeServiceHealth:
        if heartbeat is None:
            return RuntimeServiceHealth(
                service=RuntimeServiceId.HEARTBEAT,
                state=ComponentState.DISABLED,
                condition=RuntimeServiceCondition.DISABLED,
            )
        error = heartbeat.last_error
        if error is None:
            condition = (
                RuntimeServiceCondition.HEALTHY
                if heartbeat.last_success_at is not None
                else RuntimeServiceCondition.STALE
            )
            state = (
                ComponentState.READY
                if heartbeat.last_success_at is not None
                else ComponentState.STALE
            )
            local_error = None
        else:
            if isinstance(error, AuthenticationError):
                condition = RuntimeServiceCondition.AUTH_ERROR
                code = LocalErrorCode.SECRET_REVOKED
                retryable = False
            elif isinstance(error, TransportError | ServerError):
                condition = RuntimeServiceCondition.SERVER_UNAVAILABLE
                code = LocalErrorCode.DAEMON_UNAVAILABLE
                retryable = True
            else:
                condition = RuntimeServiceCondition.ERROR
                code = LocalErrorCode.INTERNAL_ERROR
                retryable = False
            state = (
                ComponentState.STALE if heartbeat.last_success_at else ComponentState.UNAVAILABLE
            )
            local_error = LocalError(
                code=code,
                message="The heartbeat service is not healthy.",
                component=ComponentId.DAEMON,
                retryable=retryable,
            )
        return RuntimeServiceHealth(
            service=RuntimeServiceId.HEARTBEAT,
            state=state,
            condition=condition,
            last_attempt_at=heartbeat.last_attempt_at,
            last_success_at=heartbeat.last_success_at,
            error=local_error,
        )
