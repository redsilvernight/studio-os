from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from studio_code_graph.graphify.runner import SubprocessRunner, sanitized_env


async def test_runs_fixed_argv_and_captures_output(tmp_path: Path) -> None:
    result = await SubprocessRunner().run(
        [sys.executable, "-c", "print('ok'); import sys; print('err', file=sys.stderr)"],
        cwd=tmp_path,
        env=sanitized_env({}),
        timeout_seconds=30,
    )
    assert result.returncode == 0 and not result.timed_out
    assert result.stdout.strip() == "ok" and result.stderr.strip() == "err"


async def test_nonzero_exit_code_is_reported(tmp_path: Path) -> None:
    result = await SubprocessRunner().run(
        [sys.executable, "-c", "raise SystemExit(3)"],
        cwd=tmp_path,
        env=sanitized_env({}),
        timeout_seconds=30,
    )
    assert result.returncode == 3


async def test_shell_metacharacters_are_not_interpreted(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    result = await SubprocessRunner().run(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", f"x & echo hi > {marker}"],
        cwd=tmp_path,
        env=sanitized_env({}),
        timeout_seconds=30,
    )
    assert result.returncode == 0 and not marker.exists()


async def test_timeout_kills_the_process(tmp_path: Path) -> None:
    started = time.monotonic()
    result = await SubprocessRunner().run(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
        env=sanitized_env({}),
        timeout_seconds=1,
    )
    assert result.timed_out
    assert time.monotonic() - started < 30


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, check=False
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def test_timeout_kills_the_whole_tree(tmp_path: Path) -> None:
    pidfile = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    result = await SubprocessRunner().run(
        [sys.executable, "-c", script], cwd=tmp_path, env=sanitized_env({}), timeout_seconds=3
    )
    assert result.timed_out
    child_pid = int(pidfile.read_text())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _alive(child_pid):
        time.sleep(0.2)
    assert not _alive(child_pid)


async def test_output_is_bounded(tmp_path: Path) -> None:
    result = await SubprocessRunner().run(
        [sys.executable, "-c", "print('x' * 200000)"],
        cwd=tmp_path,
        env=sanitized_env({}),
        timeout_seconds=30,
    )
    assert len(result.stdout) <= 16_384


def test_sanitized_env_drops_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy")
    env = sanitized_env({"GRAPHIFY_OUT": "somewhere"})
    assert "GITHUB_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env
    assert "HTTPS_PROXY" not in env
    assert env["GRAPHIFY_OUT"] == "somewhere" and env["NO_COLOR"] == "1"
