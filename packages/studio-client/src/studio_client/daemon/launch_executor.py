"""Runs an accepted launch end to end (AIB R3): report, prepare, execute and
report the terminal outcome, with a bounded and redacted excerpt and effective
cancellation.

`LaunchPuller` only decides accept/reject; this executor owns the rest:
`preparing` -> prepare the task worktree -> `running` -> start the harness
non-interactively off the event loop -> `succeeded`/`failed` with a redacted
excerpt. The pending pull never returns a terminal launch, so cancellation is
observed by re-reading each active launch by id: on `cancelled`/`expired` the
process tree is killed and no further report is sent.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from studio_contracts.task_launch import (
    LAUNCH_MAX_OUTPUT_CHARS,
    TaskLaunch,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)

from studio_client.api_client import StudioApiClient
from studio_client.daemon.launch_prepare import (
    LaunchPreparer,
    PreparationError,
    PreparationRequest,
)
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.daemon.launch_runner import (
    DEFAULT_TIMEOUT_SECONDS,
    LaunchError,
    LaunchResult,
    LaunchRunner,
    RunningLaunch,
    build_instruction,
)
from studio_client.errors import StudioApiError
from studio_client.harness.base import HarnessAdapter, HarnessContext
from studio_client.harness.redaction import redact_text, strip_ansi

logger = logging.getLogger(__name__)

TERMINAL_STATUSES: frozenset[TaskLaunchStatus] = frozenset(
    {TaskLaunchStatus.CANCELLED, TaskLaunchStatus.EXPIRED}
)


@dataclass(frozen=True)
class ResolvedLaunch:
    """Wiring-resolved material for one launch: where to work and what to run.
    `ctx` is the probing context; the executor overrides its workspace root
    with the prepared worktree before resolving the executable."""

    repo_root: Path
    task_title: str | None
    adapter: HarnessAdapter
    ctx: HarnessContext


Resolver = Callable[[TaskLaunch], Awaitable[ResolvedLaunch | None]]


class LaunchExecutor:
    def __init__(
        self,
        *,
        client: StudioApiClient,
        reporter: LaunchReporter,
        preparer: LaunchPreparer,
        runner: LaunchRunner,
        resolve: Resolver,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        poll_seconds: float = 30.0,
        secrets: Sequence[str] = (),
        max_output_chars: int = LAUNCH_MAX_OUTPUT_CHARS,
        models: Mapping[str, str] | None = None,
    ) -> None:
        self._models: Mapping[str, str] = models or {}
        self._client = client
        self._reporter = reporter
        self._preparer = preparer
        self._runner = runner
        self._resolve = resolve
        self._timeout = timeout_seconds
        self._poll = poll_seconds
        self._secrets = tuple(secret for secret in secrets if secret)
        self._max_chars = max_output_chars
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._processes: dict[UUID, RunningLaunch] = {}
        self._stopped: set[UUID] = set()
        self._watch_task: asyncio.Task[None] | None = None

    @property
    def running(self) -> int:
        return len(self._tasks)

    def start(self) -> None:
        if self._watch_task is None:
            self._watch_task = asyncio.create_task(self._watch_loop())

    async def aclose(self) -> None:
        for running in list(self._processes.values()):
            running.cancel()
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        if self._watch_task is not None:
            self._watch_task.cancel()
            await asyncio.gather(self._watch_task, return_exceptions=True)
            self._watch_task = None

    def submit(self, launch: TaskLaunch) -> None:
        """Schedule execution of an accepted launch. Idempotent per launch id."""
        if launch.id in self._tasks or launch.id in self._stopped:
            return
        self._tasks[launch.id] = asyncio.create_task(self._run(launch))

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll)
            await self._observe()

    async def _observe(self) -> None:
        for launch_id in set(self._tasks) | set(self._processes):
            if launch_id in self._stopped:
                continue
            try:
                launch = await self._client.get_task_launch(launch_id)
            except StudioApiError:
                logger.warning("launch status check failed", exc_info=True)
                continue
            if launch.status in TERMINAL_STATUSES:
                self._stop(launch_id)

    def _stop(self, launch_id: UUID) -> None:
        self._stopped.add(launch_id)
        running = self._processes.get(launch_id)
        if running is not None:
            running.cancel()
        task = self._tasks.get(launch_id)
        if task is not None and not task.done():
            task.cancel()

    async def _is_terminal(self, launch_id: UUID) -> bool:
        if launch_id in self._stopped:
            return True
        try:
            launch = await self._client.get_task_launch(launch_id)
        except StudioApiError:
            return False
        if launch.status in TERMINAL_STATUSES:
            self._stopped.add(launch_id)
            return True
        return False

    async def _run(self, launch: TaskLaunch) -> None:
        try:
            resolved = await self._resolve(launch)
            if resolved is None:
                self._reporter.report(
                    launch,
                    TaskLaunchStatus.FAILED,
                    reason_code=TaskLaunchReasonCode.PREPARATION_FAILED,
                )
                return
            if await self._is_terminal(launch.id):
                return
            self._reporter.report(launch, TaskLaunchStatus.PREPARING)
            prepared = await asyncio.to_thread(
                self._preparer.prepare,
                PreparationRequest(
                    repo_root=resolved.repo_root,
                    project_id=launch.project_id,
                    task_id=launch.task_id,
                    task_title=resolved.task_title,
                    harness_id=launch.harness_id,
                ),
            )
            if await self._is_terminal(launch.id):
                return
            worktree = prepared.worktree.path
            ctx = replace(resolved.ctx, workspace_root=worktree, probe_cwd=worktree)
            executable = resolved.adapter.resolve_executable(ctx)
            prompt = build_instruction(
                project_id=launch.project_id,
                task_id=launch.task_id,
                agent_stable_key=launch.agent_stable_key,
            )
            model = self._models.get(launch.harness_id)
            with tempfile.TemporaryDirectory(
                prefix="studio-launch-", ignore_cleanup_errors=True
            ) as isolation:
                isolation_dir = Path(isolation)
                env = {
                    **ctx.env,
                    **resolved.adapter.headless_environment(
                        ctx,
                        model=model,
                        isolation_dir=isolation_dir,
                    ),
                }
                argv = (
                    *resolved.adapter.headless_argv(prompt),
                    *resolved.adapter.headless_extra_argv(
                        ctx, model=model, isolation_dir=isolation_dir
                    ),
                )
                self._reporter.report(launch, TaskLaunchStatus.RUNNING)
                running = self._runner.start(executable, argv, worktree, env=env)
                self._processes[launch.id] = running
                result = await asyncio.to_thread(running.wait, self._timeout)
            self._report_terminal(launch, result)
        except PreparationError as error:
            logger.warning("launch preparation failed at %s", error.step)
            self._reporter.report(
                launch,
                TaskLaunchStatus.FAILED,
                reason_code=TaskLaunchReasonCode.PREPARATION_FAILED,
            )
        except LaunchError as error:
            logger.warning("launch could not start: %s", error.reason)
            self._reporter.report(
                launch,
                TaskLaunchStatus.FAILED,
                reason_code=TaskLaunchReasonCode.HARNESS_EXITED,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("launch execution failed")
            self._reporter.report(
                launch,
                TaskLaunchStatus.FAILED,
                reason_code=TaskLaunchReasonCode.HARNESS_EXITED,
            )
        finally:
            self._processes.pop(launch.id, None)
            self._tasks.pop(launch.id, None)

    def _report_terminal(self, launch: TaskLaunch, result: LaunchResult) -> None:
        if launch.id in self._stopped:
            return
        excerpt = self._excerpt(result.output)
        if result.timed_out:
            self._reporter.report(
                launch,
                TaskLaunchStatus.FAILED,
                reason_code=TaskLaunchReasonCode.EXPIRED_TIMEOUT,
                output_excerpt=excerpt,
            )
        elif result.cancelled:
            return
        elif result.exit_code == 0:
            self._reporter.report(launch, TaskLaunchStatus.SUCCEEDED, output_excerpt=excerpt)
        else:
            self._reporter.report(
                launch,
                TaskLaunchStatus.FAILED,
                reason_code=TaskLaunchReasonCode.HARNESS_EXITED,
                output_excerpt=excerpt,
            )

    def _excerpt(self, output: str) -> str:
        return redact_text(strip_ansi(output), secrets=self._secrets)[: self._max_chars]
