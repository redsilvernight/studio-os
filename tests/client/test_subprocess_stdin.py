"""The Desktop sidecar serves its bridge on stdin: a child process that inherits
that pipe blocks on Windows while the bridge thread waits for a request, so every
subprocess spawned from shipped code must redirect stdin explicitly."""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SPAWNERS = {
    "subprocess": {"run", "Popen", "check_output", "check_call", "call"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
}
_STDIN_KEYWORDS = {"stdin", "input"}


def _unredirected_spawns(source: Path) -> list[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        receiver = node.func.value
        if not isinstance(receiver, ast.Name):
            continue
        if node.func.attr not in _SPAWNERS.get(receiver.id, set()):
            continue
        if not any(keyword.arg in _STDIN_KEYWORDS for keyword in node.keywords):
            found.append(f"{source.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


def test_every_shipped_subprocess_redirects_stdin() -> None:
    offenders = [
        spawn
        for source in sorted(REPO_ROOT.glob("packages/*/src/**/*.py"))
        for spawn in _unredirected_spawns(source)
    ]
    assert offenders == []


@pytest.mark.skipif(sys.platform != "win32", reason="the stdin pipe hang is Windows-specific")
def test_git_watcher_reads_while_a_thread_blocks_on_stdin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["init", "-q"],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, stdin=subprocess.DEVNULL)
    script = textwrap.dedent(
        f"""
        import sys, threading
        from pathlib import Path
        from studio_client.watchers.git_watcher import _read_sync
        threading.Thread(target=sys.stdin.readline, daemon=True).start()
        state = _read_sync(Path({str(repo)!r}))
        print("ok" if state is not None else "none", flush=True)
        """
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    watchdog = threading.Timer(30, child.kill)
    watchdog.start()
    try:
        assert child.stdout is not None
        line = child.stdout.readline().strip()
    finally:
        watchdog.cancel()
        child.kill()
        child.communicate()
    assert line == "ok"
