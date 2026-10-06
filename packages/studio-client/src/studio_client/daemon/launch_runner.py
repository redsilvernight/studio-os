"""Non-interactive execution of a launched harness inside the prepared task
worktree (AIB R3).

This module owns the *process*: it builds the neutral instruction the agent
receives, starts the harness once with `stdin` closed (so it can never wait on
a human), merges its output into a bounded buffer, enforces a hard timeout and
kills the whole process tree on timeout or cancellation. It is deliberately
synchronous, blocking work: the daemon runs it via `asyncio.to_thread`, never
inline in the event loop.

What this module does not do — reporting the launch status, redacting the
excerpt before it leaves the machine, and reacting to a requester cancellation
— belongs to the surrounding executor.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

DEFAULT_TIMEOUT_SECONDS = 3600.0
MAX_OUTPUT_BYTES = 64 * 1024
_READ_CHUNK = 4096
_UNSUPPORTED_LAUNCHER_SUFFIXES = (".cmd", ".bat")


class LaunchError(RuntimeError):
    """The harness could not even be started. `reason` is a stable token, never
    a raw exception message; a command line never reaches it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LaunchResult:
    """Outcome of one non-interactive run. `output` is bounded but not yet
    redacted; `exit_code` is `None` only when the process was force-killed."""

    exit_code: int | None
    timed_out: bool
    cancelled: bool
    output: str
    truncated: bool


def build_instruction(
    *,
    project_id: UUID,
    task_id: UUID,
    agent_stable_key: str | None = None,
) -> str:
    """The neutral consigne given to a launched harness: resume this task with
    the L1 identity already injected by the harness hook, work in the task
    worktree, close with a handoff, and never push or merge. Ids and a stable
    key only — no shell line, path or secret is embedded."""
    lines = [
        "Tu es lancé par Studi'OS pour reprendre une tâche.",
        f"project_id : {project_id}",
        f"task_id : {task_id}",
    ]
    if agent_stable_key:
        lines.append(f"AgentDefinition attendue : {agent_stable_key}")
    lines += [
        "Commence par `studio_start_work` (mêmes project_id et task_id ; "
        "agent_id fourni par le harness), travaille dans le worktree courant, "
        "puis termine par `studio_handoff`.",
        "Aucun push, merge ou rebase automatique.",
    ]
    return "\n".join(lines)


class _Sink:
    """A bounded sink: keeps the first `limit` bytes and remembers whether more
    arrived, while always draining the stream so the child never blocks."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._buffer = bytearray()
        self._truncated = False

    def drain(self, stream: object) -> None:
        read = getattr(stream, "read", None)
        if read is None:
            return
        while True:
            chunk = read(_READ_CHUNK)
            if not chunk:
                return
            room = self._limit - len(self._buffer)
            if room > 0:
                self._buffer.extend(chunk[:room])
            if len(chunk) > max(room, 0):
                self._truncated = True

    @property
    def text(self) -> str:
        return bytes(self._buffer).decode("utf-8", errors="replace")

    @property
    def truncated(self) -> bool:
        return self._truncated


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(Exception):
        if sys.platform == "win32":
            subprocess.run(  # noqa: S603
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],  # noqa: S607
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=5,
                check=False,
            )
        else:
            os.killpg(process.pid, 9)
    with contextlib.suppress(Exception):
        process.kill()


class RunningLaunch:
    """A started harness process. `wait` enforces the timeout; `cancel` stops
    it early (a requester cancellation, or daemon shutdown)."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        sink: _Sink,
        reader: threading.Thread,
    ) -> None:
        self._process = process
        self._sink = sink
        self._reader = reader
        self._cancelled = False

    @property
    def pid(self) -> int:
        return self._process.pid

    def cancel(self) -> None:
        self._cancelled = True
        _kill_tree(self._process)

    def wait(self, timeout: float) -> LaunchResult:
        timed_out = False
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(self._process)
            with contextlib.suppress(Exception):
                self._process.wait(timeout=5)
        finally:
            self._reader.join(timeout=2)
            if self._process.stdout is not None:
                with contextlib.suppress(Exception):
                    self._process.stdout.close()
        killed = timed_out or self._cancelled
        return LaunchResult(
            exit_code=None if killed else self._process.returncode,
            timed_out=timed_out,
            cancelled=self._cancelled,
            output=self._sink.text,
            truncated=self._sink.truncated,
        )


class LaunchRunner:
    """Starts a harness executable in a task worktree with an inherited,
    non-interactive environment. `run` is the blocking convenience; `start`
    exposes the handle when the caller needs to cancel it."""

    def __init__(self, *, limit_bytes: int = MAX_OUTPUT_BYTES) -> None:
        self._limit_bytes = limit_bytes

    def start(
        self,
        executable: Path | str,
        argv: Sequence[str],
        cwd: Path | str,
        *,
        env: Mapping[str, str] | None = None,
    ) -> RunningLaunch:
        exe = Path(executable)
        if exe.suffix.lower() in _UNSUPPORTED_LAUNCHER_SUFFIXES:
            # cmd.exe re-parses the line, and the prompt would be injectable.
            raise LaunchError("unsupported_launcher")
        child_env = dict(os.environ if env is None else env)
        child_env["NO_COLOR"] = "1"
        try:
            if sys.platform == "win32":
                process = subprocess.Popen(  # noqa: S603
                    [str(exe), *argv],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=str(cwd),
                    env=child_env,
                    shell=False,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                    ),
                )
            else:
                process = subprocess.Popen(  # noqa: S603
                    [str(exe), *argv],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=str(cwd),
                    env=child_env,
                    shell=False,
                    start_new_session=True,
                )
        except OSError as error:
            raise LaunchError("not_executable") from error
        sink = _Sink(self._limit_bytes)
        reader = threading.Thread(target=sink.drain, args=(process.stdout,), daemon=True)
        reader.start()
        return RunningLaunch(process, sink, reader)

    def run(
        self,
        executable: Path | str,
        argv: Sequence[str],
        cwd: Path | str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        env: Mapping[str, str] | None = None,
    ) -> LaunchResult:
        return self.start(executable, argv, cwd, env=env).wait(timeout)
