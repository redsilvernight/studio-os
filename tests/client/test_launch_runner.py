from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.daemon.launch_runner import (
    LaunchError,
    LaunchRunner,
    build_instruction,
)
from studio_client.harness.base import (
    AdapterRefusal,
    HarnessAdapter,
    HarnessContext,
)
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.codex import CodexAdapter
from studio_client.harness.opencode import OpenCodeAdapter

PROJECT = uuid4()
TASK = uuid4()


def test_instruction_names_the_task_and_the_loop() -> None:
    text = build_instruction(project_id=PROJECT, task_id=TASK)
    assert str(PROJECT) in text
    assert str(TASK) in text
    assert "studio_start_work" in text
    assert "studio_handoff" in text
    assert "push" in text and "merge" in text


def test_instruction_carries_the_optional_stable_key() -> None:
    with_key = build_instruction(project_id=PROJECT, task_id=TASK, agent_stable_key="dev-agent")
    assert "dev-agent" in with_key
    assert "dev-agent" not in build_instruction(project_id=PROJECT, task_id=TASK)


@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        (
            ClaudeCodeAdapter(),
            (
                "-p",
                "do the work",
                "--output-format",
                "text",
                "--permission-mode",
                "acceptEdits",
                "--allowedTools",
                "Read,Edit,Write,Bash,Grep,Glob",
            ),
        ),
        (OpenCodeAdapter(), ("run", "--auto", "do the work")),
        (CodexAdapter(), ("-a", "never", "exec", "--sandbox", "workspace-write", "do the work")),
    ],
)
def test_each_adapter_has_a_bounded_headless_invocation(
    adapter: HarnessAdapter, expected: tuple[str, ...]
) -> None:
    assert adapter.headless_argv("do the work") == expected


def test_default_headless_argv_refuses() -> None:
    class Bare(HarnessAdapter):
        adapter_id = "bare"
        harness_id = "bare"
        display_name = "Bare"

        def detect(self, ctx: HarnessContext):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def plan(self, ctx: HarnessContext, *, renew: bool = False):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def read_user_entry(self, ctx: HarnessContext):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def write_user_entry(self, ctx: HarnessContext, entry: dict[str, object]) -> None:
            raise NotImplementedError

        def remove_user_entry(self, ctx: HarnessContext) -> None:
            raise NotImplementedError

        def build_entry(self, mcp_url: str, token: str) -> dict[str, object]:
            raise NotImplementedError

    with pytest.raises(AdapterRefusal) as excinfo:
        Bare().headless_argv("x")
    assert excinfo.value.reason == "headless_unsupported"


def test_resolve_executable_finds_it_outside_the_workspace(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text("", encoding="utf-8")
    (bindir / "claude.exe").write_text("", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = HarnessContext(
        workspace_root=workspace,
        mcp_url="http://127.0.0.1/mcp",
        env={"PATH": str(bindir)},
        probe_cwd=workspace,
        home=tmp_path,
    )
    found = ClaudeCodeAdapter().resolve_executable(ctx)
    assert found.parent == bindir


def test_resolve_executable_refuses_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "claude").write_text("", encoding="utf-8")
    (workspace / "claude.exe").write_text("", encoding="utf-8")
    ctx = HarnessContext(
        workspace_root=workspace,
        mcp_url="http://127.0.0.1/mcp",
        env={"PATH": str(workspace)},
        probe_cwd=workspace,
        home=tmp_path,
    )
    with pytest.raises(AdapterRefusal) as excinfo:
        ClaudeCodeAdapter().resolve_executable(ctx)
    assert excinfo.value.reason == "executable_not_found"


def test_runner_captures_output_and_exit_code(tmp_path: Path) -> None:
    result = LaunchRunner().run(
        sys.executable, ("-c", "print('hello studio')"), tmp_path, timeout=30
    )
    assert result.exit_code == 0
    assert "hello studio" in result.output
    assert result.timed_out is False
    assert result.cancelled is False
    assert result.truncated is False


def test_runner_reports_a_nonzero_exit(tmp_path: Path) -> None:
    result = LaunchRunner().run(
        sys.executable, ("-c", "import sys; sys.exit(3)"), tmp_path, timeout=30
    )
    assert result.exit_code == 3
    assert result.timed_out is False


def test_runner_kills_on_timeout(tmp_path: Path) -> None:
    result = LaunchRunner().run(
        sys.executable, ("-c", "import time; time.sleep(30)"), tmp_path, timeout=0.5
    )
    assert result.timed_out is True
    assert result.exit_code is None


def test_runner_bounds_the_output(tmp_path: Path) -> None:
    result = LaunchRunner(limit_bytes=1024).run(
        sys.executable, ("-c", "print('x' * 200000)"), tmp_path, timeout=30
    )
    assert result.truncated is True
    assert len(result.output) <= 1024


def test_runner_cancels_a_running_process(tmp_path: Path) -> None:
    runner = LaunchRunner()
    running = runner.start(sys.executable, ("-c", "import time; time.sleep(30)"), tmp_path)
    running.cancel()
    result = running.wait(timeout=10)
    assert result.cancelled is True


def test_runner_refuses_a_cmd_launcher(tmp_path: Path) -> None:
    with pytest.raises(LaunchError) as excinfo:
        LaunchRunner().start(Path("claude.cmd"), ("-p", "x"), tmp_path)
    assert excinfo.value.reason == "unsupported_launcher"


def test_runner_reports_a_missing_executable(tmp_path: Path) -> None:
    with pytest.raises(LaunchError) as excinfo:
        LaunchRunner().start(Path("studio-does-not-exist"), (), tmp_path)
    assert excinfo.value.reason == "not_executable"
