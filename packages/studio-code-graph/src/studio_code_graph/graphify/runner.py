from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_OUTPUT_LIMIT = 16_384
_INHERITED_ENV = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
    "VIRTUAL_ENV",
)


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class ProcessRunner(Protocol):
    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: float,
    ) -> RunResult: ...


def sanitized_env(extra: Mapping[str, str]) -> dict[str, str]:
    """A minimal environment: nothing the user exported for other tools (tokens,
    API keys, proxies) reaches the provider process."""
    env = {name: os.environ[name] for name in _INHERITED_ENV if name in os.environ}
    env.update({"NO_COLOR": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    env.update(extra)
    return env


def _kill_tree(process: asyncio.subprocess.Process) -> None:
    pid = process.pid
    if process.returncode is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    try:
        process.kill()
    except ProcessLookupError:
        return


def _decode(data: bytes) -> str:
    return data[:_OUTPUT_LIMIT].decode("utf-8", errors="replace")


class SubprocessRunner:
    """Runs a fixed argv (never a shell string) with a timeout. On timeout or
    cancellation the whole process tree is killed, so an interrupted provider
    leaves no orphan behind."""

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: float,
    ) -> RunResult:
        creation: dict[str, object] = {}
        if sys.platform == "win32":
            creation["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            creation["start_new_session"] = True
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=dict(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **creation,  # type: ignore[arg-type]
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
        except TimeoutError:
            await asyncio.to_thread(_kill_tree, process)
            await process.wait()
            return RunResult(-1, "", "", timed_out=True)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(_kill_tree, process))
            raise
        return RunResult(
            process.returncode if process.returncode is not None else -1,
            _decode(stdout),
            _decode(stderr),
        )
