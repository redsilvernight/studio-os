"""P04-snapshot-capture (DEC-0199): each instrumented launch leaves one
immutable execution snapshot, observed from git rather than declared, with the
preview/applied profile difference visible and no secret or prompt copied."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from studio_client.daemon.launch_executor import LaunchExecutor, ResolvedLaunch
from studio_client.daemon.launch_policy import LaunchProfile
from studio_client.daemon.launch_prepare import (
    LaunchPreparer,
    Worktree,
    WorktreeObservation,
    observe_worktree,
)
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.daemon.launch_runner import LaunchRunner
from studio_client.daemon.launch_snapshot import SnapshotInputs, build_snapshot_payload
from studio_client.harness.base import Detection, DetectionState, HarnessContext
from studio_client.outbox import OutboxStore
from studio_client.outbox.models import OutboxTable
from studio_client.outbox.store import connect
from studio_contracts.execution_snapshot import (
    ExecutionSnapshotPayload,
    SnapshotCaptureErrorCode,
    SnapshotCaptureStatus,
    content_hash,
)
from studio_contracts.library import LibraryKind
from studio_contracts.profiles import (
    MachinePolicy,
    ProfileElement,
    pin_profile,
    reference_work_profile,
)
from studio_contracts.resolution import ResolvedAgentDefinition
from studio_contracts.task_launch import TaskLaunch

from tests.client.test_launch_executor import FakeAdapter, FakeClient, _launch, _repo
from tests.contracts.test_execution_snapshot_contract import SECRET_PROMPT, _definition

CANARY = "sk-canary0123456789abcdefXYZ"
POLICY = MachinePolicy(
    opt_in=True,
    max_concurrent=1,
    allowed_harnesses=["fake"],
    permissions=["read", "write", "execute", "network", "launch"],
)


class VersionedAdapter(FakeAdapter):
    def detect(self, ctx: HarnessContext) -> Any:
        return Detection(state=DetectionState.CONFIGURED, version="1.2.3")


class ResolvingClient(FakeClient):
    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.fail = fail

    async def resolve_agent(
        self, stable_key: str, *, project_id: UUID | None = None
    ) -> ResolvedAgentDefinition:
        if self.fail:
            raise RuntimeError(f"resolver down {CANARY}")
        return _definition()


def _profile(*, resolved_version: int = 1) -> LaunchProfile:
    work = reference_work_profile("coding", "architect")

    def element(version: int) -> ProfileElement:
        return ProfileElement(
            kind=LibraryKind.AGENT_DEFINITION,
            stable_key="architect",
            version=version,
            origin="library",
        )

    return LaunchProfile(
        expected=pin_profile(work, [element(1)]),
        resolved=pin_profile(work, [element(resolved_version)]),
        permissions=tuple(work.permissions),
    )


def _executor(
    tmp_path: Path,
    repo: Path,
    *,
    client: FakeClient | None = None,
    profile: LaunchProfile | None = None,
    title: str = "Demo task",
    env: dict[str, str] | None = None,
    store_name: str = "outbox.sqlite3",
) -> tuple[LaunchExecutor, OutboxStore]:
    store = OutboxStore(connect(tmp_path / store_name))
    adapter = VersionedAdapter(("-c", "print('ok')"))

    async def resolve(launch: TaskLaunch) -> ResolvedLaunch | None:
        return ResolvedLaunch(
            repo_root=repo,
            task_title=title,
            adapter=adapter,
            ctx=HarnessContext(
                workspace_root=repo, mcp_url="http://x", env=env or {}, probe_cwd=repo
            ),
            profile=profile,
        )

    executor = LaunchExecutor(
        client=client or ResolvingClient(),  # type: ignore[arg-type]
        reporter=LaunchReporter(store),
        preparer=LaunchPreparer(fetch=False),
        runner=LaunchRunner(),
        resolve=resolve,
        machine_policy=lambda: POLICY,
        capture_snapshots=True,
    )
    return executor, store


def _with_agent(launch: TaskLaunch) -> TaskLaunch:
    return launch.model_copy(update={"agent_stable_key": "builder"})


async def _run(executor: LaunchExecutor, launch: TaskLaunch) -> None:
    executor.submit(launch)
    await executor._tasks[launch.id]


def _snapshots(store: OutboxStore) -> list[Any]:
    return [
        row
        for row in store.list_pending(OutboxTable.MUTATIONS)
        if str(row.extra.get("path")).endswith("/snapshot")
    ]


def _payload(store: OutboxStore) -> ExecutionSnapshotPayload:
    rows = _snapshots(store)
    assert len(rows) == 1
    return ExecutionSnapshotPayload.model_validate(rows[0].payload)


def _git_out(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()


def _codes(payload: ExecutionSnapshotPayload) -> set[SnapshotCaptureErrorCode]:
    return {error.code for error in payload.capture_errors}


# --- criterion 2: worktree and commit proven from git ----------------------------


async def test_full_capture_is_ok_and_reads_commit_and_branch_from_git(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    executor, store = _executor(tmp_path, repo, profile=_profile())
    launch = _with_agent(_launch())
    await _run(executor, launch)

    statuses = [
        row.payload.get("status")
        for row in store.list_pending(OutboxTable.MUTATIONS)
        if "status" in row.payload
    ]
    assert statuses == ["preparing", "running", "succeeded"]
    payload = _payload(store)
    assert payload.capture_status is SnapshotCaptureStatus.OK, payload.capture_errors
    applied = payload.applied
    assert applied is not None
    worktree = repo.parent / f"project-wt-{launch.task_id.hex[:8]}"
    assert applied.git_sha == _git_out(worktree, "rev-parse", "HEAD")
    assert applied.worktree_branch == _git_out(worktree, "symbolic-ref", "--short", "HEAD")
    assert applied.git_dirty is False
    assert applied.harness_version == "1.2.3"
    assert applied.access_mode == "workspace_write"
    assert payload.profile_drift is False
    assert payload.resolution is not None
    assert payload.resolution.agent_stable_key == "builder"


def test_declared_branch_is_never_trusted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git_out(repo, "rev-parse", "HEAD")

    lying = observe_worktree(Worktree(repo, "task/deadbeef-other", created=False))
    assert lying.git_sha == head
    assert lying.branch == "dev"
    assert lying.problem == "branch_mismatch"

    nested = repo / "sub"
    nested.mkdir()
    foreign = observe_worktree(Worktree(nested, "dev", created=False))
    assert foreign.git_sha is None
    assert foreign.problem == "toplevel_mismatch"

    payload = build_snapshot_payload(
        SnapshotInputs(
            harness_id="fake",
            agent_stable_key="builder",
            definition=_definition(),
            harness_version="1",
            worktree=lying,
            local_policy=POLICY,
        )
    )
    assert payload.capture_status is SnapshotCaptureStatus.PARTIAL
    assert _codes(payload) == {SnapshotCaptureErrorCode.WORKTREE_UNVERIFIED}
    assert payload.applied is not None and payload.applied.worktree_branch == "dev"


def test_dirty_worktree_is_reported(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    observed = observe_worktree(Worktree(repo, "dev", created=False))
    assert observed.verified
    assert observed.dirty is True


# --- criterion 2: preview/applied difference, profile mutated before start -------


async def test_profile_mutated_between_admission_and_start_is_visible(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    profile = _profile(resolved_version=2)
    executor, store = _executor(tmp_path, repo, profile=profile)
    await _run(executor, _with_agent(_launch()))

    payload = _payload(store)
    assert payload.capture_status is SnapshotCaptureStatus.PARTIAL
    assert payload.profile_drift is True
    assert payload.resolution is not None and payload.resolution.profile is not None
    assert payload.applied is not None and payload.applied.profile is not None
    assert payload.resolution.profile.digest == profile.expected.digest
    assert payload.applied.profile.digest == profile.resolved.digest
    assert payload.applied.access_mode is None
    assert payload.applied.git_sha is None
    git_errors = [
        e for e in payload.capture_errors if e.code is SnapshotCaptureErrorCode.GIT_SHA_UNAVAILABLE
    ]
    assert [e.detail for e in git_errors] == ["profile_refused"]
    statuses = [row.payload.get("status") for row in store.list_pending(OutboxTable.MUTATIONS)]
    assert "running" not in statuses


# --- criterion 1: replay gives the same snapshot and one provenance --------------


async def test_two_runs_give_the_same_snapshot_and_one_outbox_row(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    launch = _with_agent(_launch())
    first, store_a = _executor(tmp_path, repo, profile=_profile(), store_name="a.sqlite3")
    await _run(first, launch)
    second, store_b = _executor(tmp_path, repo, profile=_profile(), store_name="b.sqlite3")
    await _run(second, launch)

    a, b = _payload(store_a), _payload(store_b)
    assert content_hash(a) == content_hash(b)
    assert _snapshots(store_a)[0].id == _snapshots(store_b)[0].id

    reporter = LaunchReporter(store_a)
    assert reporter.snapshot(launch, a) is False
    assert len(_snapshots(store_a)) == 1


async def test_without_capture_flag_nothing_is_enqueued(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    executor, store = _executor(tmp_path, repo)
    executor._capture_snapshots = False
    await _run(executor, _launch())
    assert _snapshots(store) == []


async def test_launch_without_agent_is_partial_not_failed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    executor, store = _executor(tmp_path, repo)
    await _run(executor, _launch())
    payload = _payload(store)
    assert payload.capture_status is SnapshotCaptureStatus.PARTIAL
    assert payload.resolution is None
    assert SnapshotCaptureErrorCode.RESOLUTION_UNAVAILABLE in _codes(payload)
    assert payload.applied is not None and payload.applied.git_sha is not None


# --- criterion 3: canary secrets and private prompts never leave the machine -----


async def test_canary_secret_and_prompt_are_absent_from_payload_and_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    repo = _repo(tmp_path)
    executor, store = _executor(
        tmp_path,
        repo,
        client=ResolvingClient(fail=True),
        title=f"Leak {CANARY}",
        env={"OPENAI_API_KEY": CANARY, "STUDIO_CLIENT_MACHINE_TOKEN": CANARY},
    )
    await _run(executor, _with_agent(_launch()))

    payload = _payload(store)
    raw = json.dumps(_snapshots(store)[0].payload)
    assert CANARY not in raw
    assert CANARY.lower() not in raw
    assert SECRET_PROMPT not in raw
    assert str(tmp_path) not in raw
    assert CANARY not in caplog.text and CANARY.lower() not in caplog.text
    assert SnapshotCaptureErrorCode.REDACTION_REQUIRED in _codes(payload)
    assert payload.applied is not None and payload.applied.worktree_branch is None
    resolution_errors = [
        e
        for e in payload.capture_errors
        if e.code is SnapshotCaptureErrorCode.RESOLUTION_UNAVAILABLE
    ]
    assert [e.detail for e in resolution_errors] == ["resolver_unreachable"]


def test_prompt_body_becomes_a_digest_only() -> None:
    payload = build_snapshot_payload(
        SnapshotInputs(
            harness_id="fake",
            agent_stable_key="builder",
            definition=_definition(),
            harness_version="1",
            worktree=None,
            not_prepared="preparation_failed:worktree",
            local_policy=POLICY,
        )
    )
    raw = payload.model_dump_json()
    assert SECRET_PROMPT not in raw
    assert payload.resolution is not None and payload.resolution.resources
    assert [e.detail for e in payload.capture_errors] == ["preparation_failed:worktree"]


def test_unsafe_projection_target_is_dropped_and_named() -> None:
    inputs = SnapshotInputs(
        harness_id="fake",
        harness_version="1",
        worktree=WorktreeObservation("a" * 40, "task/x", False),
        projections=[("C:/Users/me/.claude/x.md", "sha256:" + "0" * 64)],
        local_policy=POLICY,
    )
    payload = build_snapshot_payload(inputs)
    assert payload.applied is not None and payload.applied.projections == []
    assert SnapshotCaptureErrorCode.REDACTION_REQUIRED in _codes(payload)
    assert "Users" not in payload.model_dump_json()
