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
import hashlib
import json
import logging
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from studio_contracts.auth import AgentCreate
from studio_contracts.profiles import MachinePolicy
from studio_contracts.task_launch import (
    LAUNCH_MAX_OUTPUT_CHARS,
    TaskLaunch,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)

from studio_client.api_client import StudioApiClient
from studio_client.daemon.launch_policy import LaunchProfile, enforce_profile, run_diagnostics
from studio_client.daemon.launch_prepare import (
    LaunchPreparer,
    PreparationError,
    PreparationRequest,
    Worktree,
    projection_digests,
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
from studio_client.daemon.launch_snapshot import SnapshotInputs, build_snapshot_payload
from studio_client.errors import StudioApiError
from studio_client.harness.base import AccessMode, HarnessAdapter, HarnessContext
from studio_client.harness.probe import launch_environment
from studio_client.harness.redaction import redact_text, strip_ansi
from studio_client.usage.collectors import RunObservation
from studio_client.usage.recorder import LaunchUsageRecorder

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
    profile: LaunchProfile | None = None


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
        usage: LaunchUsageRecorder | None = None,
        machine_policy: Callable[[], MachinePolicy] | None = None,
        capture_snapshots: bool = False,
    ) -> None:
        self._capture_snapshots = capture_snapshots
        self._usage = usage
        self._machine_policy = machine_policy
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

    def owns(self, launch_id: UUID) -> bool:
        """Whether this executor runs the launch (P02 restart reconciliation)."""
        return launch_id in self._tasks or launch_id in self._processes

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
        resolved: ResolvedLaunch | None = None
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
            enforcement = enforce_profile(
                resolved.profile,
                supported_modes=resolved.adapter.access_modes,
                policy=self._policy(),
            )
            if enforcement.mode is None:
                logger.warning("launch refused by local profile policy: %s", enforcement.refusal)
                await self._capture_snapshot(launch, resolved, not_prepared="profile_refused")
                self._reporter.report(
                    launch,
                    TaskLaunchStatus.FAILED,
                    reason_code=TaskLaunchReasonCode.PREPARATION_FAILED,
                    output_excerpt=(
                        f"[studio:profile_refused] reason={enforcement.refusal} "
                        f"{enforcement.diagnostic}"
                    )[: self._max_chars],
                )
                return
            mode = enforcement.mode
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
            await self._capture_snapshot(
                launch, resolved, mode=mode, ctx=ctx, worktree=prepared.worktree
            )
            executable = resolved.adapter.resolve_executable(ctx)
            model = self._models.get(launch.harness_id)
            agent_id = await self._ensure_launch_agent(launch.harness_id, model)
            prompt = build_instruction(
                project_id=launch.project_id,
                task_id=launch.task_id,
                agent_id=agent_id,
                agent_stable_key=launch.agent_stable_key,
            )
            credential = await self._client.issue_launch_credential(launch.id)
            with tempfile.TemporaryDirectory(
                prefix="studio-launch-", ignore_cleanup_errors=True
            ) as isolation:
                isolation_dir = Path(isolation)
                env = {
                    **launch_environment(ctx.env),
                    **resolved.adapter.headless_environment(
                        ctx,
                        model=model,
                        isolation_dir=isolation_dir,
                        credential=credential.token,
                    ),
                }
                argv = (
                    *resolved.adapter.headless_argv(prompt, mode=mode),
                    *resolved.adapter.headless_extra_argv(
                        ctx, model=model, isolation_dir=isolation_dir, mode=mode
                    ),
                )
                self._reporter.report(launch, TaskLaunchStatus.RUNNING)
                running = self._runner.start(executable, argv, worktree, env=env)
                self._processes[launch.id] = running
                result = await asyncio.to_thread(running.wait, self._timeout)
            display = self._record_usage(launch, result)
            self._report_terminal(
                launch, result, mode=mode, extra_secrets=(credential.token,), display=display
            )
        except PreparationError as error:
            logger.warning("launch preparation failed at %s", error.step)
            if resolved is not None:
                await self._capture_snapshot(
                    launch, resolved, not_prepared=f"preparation_failed:{error.step}"
                )
            self._reporter.report(
                launch,
                TaskLaunchStatus.FAILED,
                reason_code=TaskLaunchReasonCode.PREPARATION_FAILED,
                output_excerpt=(
                    "[studio:agent_identity_unavailable]"
                    if error.step == "agent_identity"
                    else None
                ),
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

    async def _ensure_launch_agent(self, harness_id: str, model: str | None) -> UUID:
        identity = json.dumps(
            {"harness": harness_id, "model": model}, sort_keys=True, separators=(",", ":")
        )
        stable_key = f"launch-agent-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
        try:
            agent, _ = await self._client.ensure_agent(
                AgentCreate(
                    display_name=f"studio-{harness_id}",
                    agent_kind="worker",
                    harness=harness_id,
                    model=model,
                    stable_key=stable_key,
                )
            )
        except StudioApiError:
            raise PreparationError("agent_identity", "agent_identity_unavailable") from None
        return agent.id

    async def _capture_snapshot(
        self,
        launch: TaskLaunch,
        resolved: ResolvedLaunch,
        *,
        mode: AccessMode | None = None,
        ctx: HarnessContext | None = None,
        worktree: Worktree | None = None,
        not_prepared: str | None = None,
    ) -> None:
        if not self._capture_snapshots:
            return
        try:
            inputs = await self._snapshot_inputs(
                launch, resolved, mode=mode, ctx=ctx, worktree=worktree, not_prepared=not_prepared
            )
            payload = build_snapshot_payload(inputs)
            self._reporter.snapshot(launch, payload)
            logger.info(
                "launch snapshot captured: status=%s reason=%s",
                payload.capture_status.value,
                not_prepared or "prepared",
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.warning("launch snapshot capture failed: reason=%s", not_prepared or "prepared")

    async def _snapshot_inputs(
        self,
        launch: TaskLaunch,
        resolved: ResolvedLaunch,
        *,
        mode: AccessMode | None,
        ctx: HarnessContext | None,
        worktree: Worktree | None,
        not_prepared: str | None,
    ) -> SnapshotInputs:
        definition = None
        definition_error = None
        if launch.agent_stable_key:
            try:
                definition = await self._client.resolve_agent(
                    launch.agent_stable_key, project_id=launch.project_id
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                definition_error = "resolver_unreachable"
        observed = projections = None
        if worktree is not None:
            observed = await asyncio.to_thread(self._preparer.observe, worktree)
            projections = await asyncio.to_thread(projection_digests, worktree.path)
        profile = resolved.profile
        try:
            policy: MachinePolicy | None = self._policy()
        except Exception:  # noqa: BLE001
            policy = None
        return SnapshotInputs(
            harness_id=launch.harness_id,
            agent_stable_key=launch.agent_stable_key,
            definition=definition,
            definition_error=definition_error,
            preview_profile=None if profile is None else profile.expected,
            applied_profile=None if profile is None else profile.resolved,
            access_mode=None if mode is None else mode.value,
            harness_version=await self._harness_version(resolved, ctx),
            worktree=observed,
            not_prepared=not_prepared,
            projections=projections if worktree is not None else (),
            local_policy=policy,
        )

    async def _harness_version(
        self, resolved: ResolvedLaunch, ctx: HarnessContext | None
    ) -> str | None:
        try:
            detection = await asyncio.to_thread(resolved.adapter.detect, ctx or resolved.ctx)
        except Exception:  # noqa: BLE001
            return None
        return detection.version

    def _record_usage(self, launch: TaskLaunch, result: LaunchResult) -> str | None:
        if self._usage is None:
            return None
        recorded = self._usage.record(
            launch,
            RunObservation(
                harness_id=launch.harness_id,
                output=result.output,
                truncated=result.truncated,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                cancelled=result.cancelled,
                started_at=result.started_at,
                finished_at=result.finished_at,
                duration_seconds=result.duration_seconds,
            ),
        )
        return None if recorded is None else recorded.collected.result_text

    def _policy(self) -> MachinePolicy:
        if self._machine_policy is None:
            return MachinePolicy(opt_in=False, max_concurrent=1)
        return self._machine_policy()

    def _report_terminal(
        self,
        launch: TaskLaunch,
        result: LaunchResult,
        *,
        mode: AccessMode = AccessMode.WORKSPACE_WRITE,
        extra_secrets: tuple[str, ...] = (),
        display: str | None = None,
    ) -> None:
        if launch.id in self._stopped:
            return
        # Diagnostics read the raw harness output (JSON included); the excerpt
        # shows the collector's readable result when there is one.
        diagnostics = run_diagnostics(result.output)
        header = (
            f"[studio:launch_diagnostics] mode={mode.value} {' '.join(diagnostics)}\n"
            if diagnostics
            else ""
        )
        body = self._excerpt(result.output if display is None else display, extra_secrets)
        excerpt = (header + body)[: self._max_chars]
        if result.timed_out:
            self._reporter.report(
                launch,
                TaskLaunchStatus.FAILED,
                reason_code=TaskLaunchReasonCode.EXPIRED_TIMEOUT,
                output_excerpt=excerpt,
            )
        elif result.cancelled:
            return
        elif result.exit_code == 0 and "forbidden_operation" not in diagnostics:
            self._reporter.report(launch, TaskLaunchStatus.SUCCEEDED, output_excerpt=excerpt)
        else:
            self._reporter.report(
                launch,
                TaskLaunchStatus.FAILED,
                reason_code=TaskLaunchReasonCode.HARNESS_EXITED,
                output_excerpt=excerpt,
            )

    def _excerpt(self, output: str, extra_secrets: tuple[str, ...] = ()) -> str:
        secrets = (*self._secrets, *extra_secrets)
        return redact_text(strip_ansi(output), secrets=secrets)[: self._max_chars]
