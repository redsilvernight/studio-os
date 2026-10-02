"""Bounded probes of a locally installed harness executable.

A probe finds an executable by name in trusted locations and asks it for its
version — nothing else. It never uses a shell, never runs a workspace-provided
binary, never downloads or installs, and never lets a probe outlive its
timeout or flood the caller.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

PROBE_TIMEOUT_SECONDS = 8.0
MAX_PROBE_OUTPUT_BYTES = 4096
_ALLOWED_SUFFIXES = (".exe", ".cmd") if sys.platform == "win32" else ("",)
_SHIM_SUFFIXES = (".cmd", ".bat")
_SHIM_READ_LIMIT = 16_384
_PASSTHROUGH_ENV = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SystemRoot",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
)


class ProbeFailure(Exception):
    """The executable could not be probed. `reason` is a stable token."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ProbeOutput:
    exit_code: int
    text: str


def _is_within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def _same_dir(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _native_exe_behind_shim(shim: Path) -> Path | None:
    """Follow a Windows `.cmd`/`.bat` shim (npm-style) to the native `.exe` it
    launches. A harness installed through an npm shim is launched directly
    instead of through `cmd.exe`, which the launcher refuses (cmd.exe re-parses
    the command line and the prompt could be injected). Only an existing,
    non-symlink `.exe` inside the shim's own directory tree is accepted;
    anything else returns None and the shim is kept as-is."""
    try:
        text = shim.read_text(encoding="utf-8", errors="replace")[:_SHIM_READ_LIMIT]
    except OSError:
        return None
    base = str(shim.parent)
    for raw in re.findall(r'"?([^"\r\n]+?\.exe)"?', text, flags=re.IGNORECASE):
        expanded = raw.strip().replace("%~dp0%", base).replace("%dp0%", base)
        candidate = Path(expanded)
        if not candidate.is_absolute() or candidate.suffix.lower() != ".exe":
            continue
        try:
            if (
                candidate.is_file()
                and not candidate.is_symlink()
                and _is_within(candidate.resolve(), shim.parent.resolve())
            ):
                return candidate
        except OSError:
            continue
    return None


def locate_executable(
    names: Sequence[str],
    *,
    path_env: str | None,
    excluded_dirs: Sequence[Path] = (),
) -> Path | None:
    """First regular executable named `names[i]` in an absolute PATH entry,
    skipping the working directory, relative entries and `excluded_dirs`
    (the workspace: a repository must not choose what Studi'OS launches). A
    `.cmd` shim is followed to the native `.exe` it launches when one exists in
    its own directory tree (npm layout)."""
    if not path_env:
        return None
    cwd = Path.cwd()
    excluded = [directory.resolve() for directory in excluded_dirs if directory.exists()]
    directories: list[Path] = []
    for raw in path_env.split(os.pathsep):
        entry = raw.strip().strip('"')
        if not entry or not os.path.isabs(entry):
            continue
        directory = Path(entry)
        if _same_dir(directory, cwd) or any(
            _is_within(directory.resolve(), block) for block in excluded
        ):
            continue
        directories.append(directory)
    for suffix in _ALLOWED_SUFFIXES:
        for directory in directories:
            for name in names:
                candidate = directory / f"{name}{suffix}"
                try:
                    if candidate.is_file() and not candidate.is_symlink():
                        if suffix in _SHIM_SUFFIXES:
                            native = _native_exe_behind_shim(candidate)
                            if native is not None:
                                return native
                        return candidate
                except OSError:
                    continue
    return None


def _sanitised_env(source: Mapping[str, str]) -> dict[str, str]:
    env = {key: source[key] for key in _PASSTHROUGH_ENV if key in source}
    env["NO_COLOR"] = "1"
    env["CI"] = "1"
    return env


def _drain(stream: object, sink: bytearray, limit: int) -> None:
    read = getattr(stream, "read", None)
    if read is None:
        return
    while True:
        chunk = read(1024)
        if not chunk:
            return
        room = limit - len(sink)
        if room > 0:
            sink.extend(chunk[:room])


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


def run_probe(
    executable: Path,
    args: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> ProbeOutput:
    """Run `executable args` without a shell, with a scrubbed environment, a
    neutral working directory, a hard timeout and bounded output."""
    try:
        if sys.platform == "win32":
            process = subprocess.Popen(  # noqa: S603
                [str(executable), *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=_sanitised_env(env),
                cwd=str(cwd),
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            process = subprocess.Popen(  # noqa: S603
                [str(executable), *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=_sanitised_env(env),
                cwd=str(cwd),
                shell=False,
                start_new_session=True,
            )
    except PermissionError as error:
        raise ProbeFailure("permission_denied") from error
    except OSError as error:
        raise ProbeFailure("not_executable") from error
    sink = bytearray()
    reader = threading.Thread(
        target=_drain, args=(process.stdout, sink, MAX_PROBE_OUTPUT_BYTES), daemon=True
    )
    reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        _kill_tree(process)
        raise ProbeFailure("timeout") from error
    finally:
        reader.join(timeout=2)
        if process.stdout is not None:
            with contextlib.suppress(Exception):
                process.stdout.close()
    text = bytes(sink).decode("utf-8", errors="replace")
    return ProbeOutput(exit_code=process.returncode, text=text)


def extract_version(output: ProbeOutput, identity: re.Pattern[str]) -> str:
    """The version captured by `identity` (group 'version') from the probe
    output. Output that does not match is not this harness."""
    if output.exit_code != 0:
        raise ProbeFailure("probe_failed")
    match = identity.search(output.text.strip())
    if match is None:
        raise ProbeFailure("unexpected_output")
    return match.group("version")
