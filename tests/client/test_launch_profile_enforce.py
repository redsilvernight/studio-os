"""P04-profile-enforce (DEC-0198): a server profile never widens the machine's
opt-in, allowlist or permissions; the machine decides last and fails closed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from studio_client.config import ClientConfig
from studio_client.daemon.launch_executor import LaunchExecutor, ResolvedLaunch
from studio_client.daemon.launch_policy import (
    LaunchProfile,
    enforce_profile,
    run_diagnostics,
)
from studio_client.daemon.launch_prepare import LaunchPreparer
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.daemon.launch_runner import LaunchRunner
from studio_client.daemon.launch_settings_bridge import (
    SETTINGS_FILE,
    load_launch_settings,
    load_machine_policy,
    save_launch_settings,
)
from studio_client.harness.base import (
    AccessMode,
    AdapterRefusal,
    Detection,
    DetectionState,
    HarnessContext,
)
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.codex import CodexAdapter
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.registry import HarnessRegistry
from studio_client.outbox import OutboxStore
from studio_client.outbox.models import OutboxTable
from studio_client.outbox.store import connect
from studio_contracts.library import LibraryKind
from studio_contracts.local.launch import LaunchSettingsSaveRequest
from studio_contracts.profiles import (
    MachinePolicy,
    ProfileElement,
    ProfilePermission,
    pin_profile,
    reference_work_profile,
)
from studio_contracts.task_launch import TaskLaunch

from tests.client.test_launch_executor import FakeAdapter, FakeClient, _launch, _repo

ALL: list[ProfilePermission] = ["read", "write", "execute", "network", "launch"]
BOTH = frozenset({AccessMode.READ_ONLY, AccessMode.WORKSPACE_WRITE})
WRITE_ONLY = frozenset({AccessMode.WORKSPACE_WRITE})


def _policy(permissions: list[ProfilePermission] | None, *, opt_in: bool = True) -> MachinePolicy:
    return MachinePolicy(
        opt_in=opt_in, max_concurrent=1, allowed_harnesses=["fake"], permissions=permissions
    )


def _element(version: int) -> ProfileElement:
    return ProfileElement(
        kind=LibraryKind.AGENT_DEFINITION, stable_key="architect", version=version, origin="library"
    )


def _profile(reference: str, *, resolved_version: int = 1) -> LaunchProfile:
    work = reference_work_profile(reference, "architect")
    return LaunchProfile(
        expected=pin_profile(work, [_element(1)]),
        resolved=pin_profile(work, [_element(resolved_version)]),
        permissions=tuple(work.permissions),
    )


# --- criterion 1: reconciliation never widens read-only -----------------------


def test_legacy_launch_without_profile_keeps_coding_mode() -> None:
    result = enforce_profile(None, supported_modes=WRITE_ONLY, policy=_policy(None))
    assert result.mode is AccessMode.WORKSPACE_WRITE


@pytest.mark.parametrize("adapter", [ClaudeCodeAdapter(), CodexAdapter()])
def test_read_only_profile_runs_read_only_on_a_guaranteeing_adapter(adapter: object) -> None:
    result = enforce_profile(
        _profile("architecture-read-only"),
        supported_modes=adapter.access_modes,  # type: ignore[attr-defined]
        policy=_policy(ALL),
    )
    assert result.accepted
    assert result.mode is AccessMode.READ_ONLY


def test_read_only_profile_is_refused_when_the_adapter_cannot_guarantee_it() -> None:
    result = enforce_profile(
        _profile("architecture-read-only"),
        supported_modes=OpenCodeAdapter().access_modes,
        policy=_policy(ALL),
    )
    assert result.mode is None
    assert result.refusal == "read_only_unsupported"
    assert "read_only" in result.diagnostic


def test_coding_profile_is_refused_not_widened_on_a_read_only_machine() -> None:
    result = enforce_profile(_profile("coding"), supported_modes=BOTH, policy=_policy(["read"]))
    assert result.mode is None
    assert result.refusal == "permission_denied"
    assert "write" in result.diagnostic


def test_absent_local_permissions_grant_nothing() -> None:
    result = enforce_profile(
        _profile("architecture-read-only"), supported_modes=BOTH, policy=_policy(None)
    )
    assert result.refusal == "permission_denied"


def test_machine_opt_in_off_refuses_even_a_read_only_profile() -> None:
    result = enforce_profile(
        _profile("architecture-read-only"),
        supported_modes=BOTH,
        policy=_policy(ALL, opt_in=False),
    )
    assert result.refusal == "machine_opt_in_off"


def test_claude_read_only_argv_denies_every_writing_tool(tmp_path: Path) -> None:
    adapter = ClaudeCodeAdapter()
    ctx = HarnessContext(
        workspace_root=tmp_path, mcp_url="http://x/mcp", env={}, probe_cwd=tmp_path, home=tmp_path
    )
    argv = adapter.headless_argv("p", mode=AccessMode.READ_ONLY)
    assert "acceptEdits" not in argv
    disallowed = argv[argv.index("--disallowedTools") + 1].split(",")
    assert {"Edit", "Write", "Bash", "PowerShell"} <= set(disallowed)
    extra = adapter.headless_extra_argv(
        ctx, model=None, isolation_dir=tmp_path, mode=AccessMode.READ_ONLY
    )
    allowed = extra[extra.index("--allowedTools") + 1].split(",")
    assert not {"Edit", "Write", "Bash"} & set(allowed)
    assert "Read" in allowed


def test_codex_read_only_uses_the_read_only_sandbox() -> None:
    argv = CodexAdapter().headless_argv("p", mode=AccessMode.READ_ONLY)
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "workspace-write" not in argv


def test_opencode_refuses_read_only_rather_than_running_auto() -> None:
    with pytest.raises(AdapterRefusal) as caught:
        OpenCodeAdapter().headless_argv("p", mode=AccessMode.READ_ONLY)
    assert caught.value.reason == "read_only_unsupported"


def test_write_mode_argv_is_unchanged() -> None:
    assert CodexAdapter().headless_argv("p") == (
        "-a",
        "never",
        "exec",
        "--sandbox",
        "workspace-write",
        "p",
    )
    assert OpenCodeAdapter().headless_argv("p") == ("run", "--auto", "p")


# --- criterion 2: profile changed since preview → versioned refusal -----------


def test_changed_library_version_refuses_with_profile_version_changed() -> None:
    result = enforce_profile(
        _profile("architecture-read-only", resolved_version=2),
        supported_modes=BOTH,
        policy=_policy(ALL),
    )
    assert result.mode is None
    assert result.refusal == "profile_version_changed"
    assert "expected=" in result.diagnostic and "resolved=" in result.diagnostic


def test_changed_profile_body_changes_the_digest() -> None:
    read_only = pin_profile(reference_work_profile("architecture-read-only", "architect"))
    coding = pin_profile(reference_work_profile("coding", "architect"))
    assert read_only.digest != coding.digest
    assert read_only == pin_profile(reference_work_profile("architecture-read-only", "architect"))


# --- criterion 3: diagnostics -------------------------------------------------


def test_run_diagnostics_flags_forbidden_operations_and_missing_protocol() -> None:
    assert run_diagnostics("studio-git-guard: commit direct interdit") == (
        "forbidden_operation",
        "start_work_not_observed",
        "handoff_not_observed",
    )
    assert run_diagnostics("called studio_start_work ... studio_handoff done") == ()


# --- executor: the final local decision is applied before anything runs ------


class ReadOnlyFake(FakeAdapter):
    access_modes = BOTH

    def __init__(self, argv: tuple[str, ...]) -> None:
        super().__init__(argv)
        self.modes: list[AccessMode] = []

    def headless_argv(
        self, prompt: str, *, mode: AccessMode = AccessMode.WORKSPACE_WRITE
    ) -> tuple[str, ...]:
        self.require_mode(mode)
        self.modes.append(mode)
        return self._argv

    def detect(self, ctx: HarnessContext) -> Detection:
        return Detection(state=DetectionState.CONFIGURED)


def _executor(
    tmp_path: Path,
    adapter: FakeAdapter,
    profile: LaunchProfile | None,
    policy: MachinePolicy,
) -> tuple[LaunchExecutor, OutboxStore]:
    repo = _repo(tmp_path)
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))

    async def resolve(launch: TaskLaunch) -> ResolvedLaunch | None:
        return ResolvedLaunch(
            repo_root=repo,
            task_title="Demo task",
            adapter=adapter,
            ctx=HarnessContext(workspace_root=repo, mcp_url="http://x", env={}, probe_cwd=repo),
            profile=profile,
        )

    executor = LaunchExecutor(
        client=FakeClient(),  # type: ignore[arg-type]
        reporter=LaunchReporter(store),
        preparer=LaunchPreparer(),
        runner=LaunchRunner(),
        resolve=resolve,
        timeout_seconds=30.0,
        machine_policy=lambda: policy,
    )
    return executor, store


async def _run(executor: LaunchExecutor) -> list[dict[str, object]]:
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]
    return [row.payload for row in executor._reporter._store.list_pending(OutboxTable.MUTATIONS)]


def _marker(tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    marker = tmp_path / "ran.txt"
    return marker, ("-c", f"open({str(marker)!r}, 'w').write('x')")


async def test_executor_refuses_a_changed_profile_before_preparing(tmp_path: Path) -> None:
    marker, argv = _marker(tmp_path)
    executor, _ = _executor(
        tmp_path,
        ReadOnlyFake(argv),
        _profile("architecture-read-only", resolved_version=2),
        _policy(ALL),
    )
    rows = await _run(executor)
    assert [r["status"] for r in rows] == ["failed"]
    assert rows[0]["reason_code"] == "preparation_failed"
    assert "reason=profile_version_changed" in str(rows[0]["output_excerpt"])
    assert not marker.exists()


async def test_executor_refuses_read_only_on_an_adapter_without_guarantee(tmp_path: Path) -> None:
    marker, argv = _marker(tmp_path)
    executor, _ = _executor(
        tmp_path, FakeAdapter(argv), _profile("architecture-read-only"), _policy(ALL)
    )
    rows = await _run(executor)
    assert [r["status"] for r in rows] == ["failed"]
    assert "reason=read_only_unsupported" in str(rows[0]["output_excerpt"])
    assert not marker.exists()


async def test_executor_without_machine_policy_fails_closed(tmp_path: Path) -> None:
    executor, _ = _executor(
        tmp_path, ReadOnlyFake(("-c", "print(1)")), _profile("architecture-read-only"), _policy(ALL)
    )
    executor._machine_policy = None
    rows = await _run(executor)
    assert "reason=machine_opt_in_off" in str(rows[-1]["output_excerpt"])


async def test_executor_runs_read_only_profile_in_read_only_mode(tmp_path: Path) -> None:
    adapter = ReadOnlyFake(("-c", "print('studio_start_work then studio_handoff')"))
    executor, _ = _executor(tmp_path, adapter, _profile("architecture-read-only"), _policy(ALL))
    rows = await _run(executor)
    assert [r["status"] for r in rows] == ["preparing", "running", "succeeded"]
    assert adapter.modes == [AccessMode.READ_ONLY]
    assert "launch_diagnostics" not in str(rows[-1]["output_excerpt"])


async def test_forbidden_operation_with_exit_zero_is_a_failure(tmp_path: Path) -> None:
    script = "print('studio_start_work'); print('Permission denied: Edit'); print('studio_handoff')"
    executor, _ = _executor(
        tmp_path, ReadOnlyFake(("-c", script)), _profile("architecture-read-only"), _policy(ALL)
    )
    rows = await _run(executor)
    assert rows[-1]["status"] == "failed"
    assert rows[-1]["reason_code"] == "harness_exited"
    excerpt = str(rows[-1]["output_excerpt"])
    assert excerpt.startswith("[studio:launch_diagnostics] mode=read_only forbidden_operation")


async def test_missing_protocol_calls_are_reported_not_silent(tmp_path: Path) -> None:
    executor, _ = _executor(tmp_path, FakeAdapter(("-c", "print('done')")), None, _policy(None))
    rows = await _run(executor)
    assert rows[-1]["status"] == "succeeded"
    header = str(rows[-1]["output_excerpt"]).splitlines()[0]
    assert header == (
        "[studio:launch_diagnostics] mode=workspace_write "
        "start_work_not_observed handoff_not_observed"
    )


# --- bridge: local permissions are the machine's, preserved and fail closed ---


def _config() -> ClientConfig:
    return ClientConfig(
        api_base_url="http://test", launch_opt_in=False, launch_allowed_harnesses=()
    )


def test_bridge_reads_local_permissions_and_keeps_settings_compatible(tmp_path: Path) -> None:
    (tmp_path / SETTINGS_FILE).write_text(
        json.dumps(
            {
                "opt_in": True,
                "max_concurrent": 1,
                "allowed_harnesses": ["codex"],
                "permissions": ["read"],
            }
        ),
        encoding="utf-8",
    )
    policy = load_machine_policy(_config(), tmp_path)
    assert policy.permissions == ["read"]
    settings = load_launch_settings(_config(), tmp_path)
    assert settings.opt_in is True
    assert settings.allowed_harnesses == ["codex"]


def test_bridge_without_permissions_grants_none(tmp_path: Path) -> None:
    assert load_machine_policy(_config(), tmp_path).permissions is None


def test_bridge_invalid_file_fails_closed(tmp_path: Path) -> None:
    (tmp_path / SETTINGS_FILE).write_text(
        json.dumps({"opt_in": True, "max_concurrent": 1, "permissions": ["root"]}),
        encoding="utf-8",
    )
    policy = load_machine_policy(_config(), tmp_path)
    assert policy.opt_in is False
    assert policy.permissions is None
    assert policy.allowed_harnesses == []


def test_bridge_save_preserves_local_permissions(tmp_path: Path) -> None:
    (tmp_path / SETTINGS_FILE).write_text(
        json.dumps({"opt_in": False, "max_concurrent": 1, "permissions": ["read"]}),
        encoding="utf-8",
    )
    registry = HarnessRegistry([ReadOnlyFake(("-c", sys.executable))])
    ctx = HarnessContext(workspace_root=tmp_path, mcp_url="http://x", env={}, probe_cwd=tmp_path)
    save_launch_settings(
        _config(),
        tmp_path,
        LaunchSettingsSaveRequest(
            opt_in=True, max_concurrent=2, allowed_harnesses=["fake"], confirmed=True
        ),
        registry=registry,
        ctx=ctx,
    )
    stored = json.loads((tmp_path / SETTINGS_FILE).read_text(encoding="utf-8"))
    assert stored["permissions"] == ["read"]
    assert stored["opt_in"] is True


def test_bridge_save_without_permissions_writes_an_n1_compatible_file(tmp_path: Path) -> None:
    registry = HarnessRegistry([ReadOnlyFake(("-c", sys.executable))])
    ctx = HarnessContext(workspace_root=tmp_path, mcp_url="http://x", env={}, probe_cwd=tmp_path)
    save_launch_settings(
        _config(),
        tmp_path,
        LaunchSettingsSaveRequest(
            opt_in=True, max_concurrent=1, allowed_harnesses=["fake"], confirmed=True
        ),
        registry=registry,
        ctx=ctx,
    )
    stored = json.loads((tmp_path / SETTINGS_FILE).read_text(encoding="utf-8"))
    assert "permissions" not in stored
