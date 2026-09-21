from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from studio_code_graph.graphify.runner import sanitized_env
from studio_code_graph.provider import ProbeState, ProviderProbe

EXECUTABLE_ENV = "STUDIO_CODE_GRAPH_GRAPHIFY_EXE"
"""Optional daemon-side override of where the separately managed Graphify
install lives. Set by the operator of the daemon, never by the renderer."""

MIN_SUPPORTED = (0, 9, 0)
MAX_SUPPORTED_EXCLUSIVE = (1, 0, 0)
TESTED_VERSION = "0.9.59"

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_PROBE_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class GraphifyInstall:
    executable: Path
    version: str


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(text)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def resolve_executable(configured: Path | None = None) -> Path | None:
    """The Graphify executable to use: an explicit path, the operator override,
    then a plain `PATH` lookup. Nothing is downloaded or installed, and no
    developer-machine location is ever assumed."""
    candidates: list[str | None] = [str(configured) if configured else None]
    candidates.append(os.environ.get(EXECUTABLE_ENV))
    for raw in candidates:
        if raw:
            path = Path(raw)
            return path if path.is_absolute() and path.is_file() else None
    found = shutil.which("graphify")
    return Path(found) if found else None


def probe_install(configured: Path | None = None) -> tuple[ProviderProbe, GraphifyInstall | None]:
    executable = resolve_executable(configured)
    if executable is None:
        return ProviderProbe(ProbeState.NOT_INSTALLED, reason="graphify executable not found"), None
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
            stdin=subprocess.DEVNULL,
            env=sanitized_env({}),
        )
    except subprocess.TimeoutExpired:
        return ProviderProbe(ProbeState.UNAVAILABLE, reason="graphify did not answer in time"), None
    except OSError:
        return ProviderProbe(ProbeState.UNAVAILABLE, reason="graphify could not be started"), None
    output = f"{result.stdout}\n{result.stderr}"
    version = parse_version(output)
    if result.returncode != 0 or version is None:
        return ProviderProbe(
            ProbeState.UNAVAILABLE, reason="graphify did not report a version"
        ), None
    text = ".".join(str(part) for part in version)
    if not MIN_SUPPORTED <= version < MAX_SUPPORTED_EXCLUSIVE:
        return (
            ProviderProbe(
                ProbeState.INCOMPATIBLE,
                version=text,
                reason=f"graphify {text} is outside the supported range "
                f">={_join(MIN_SUPPORTED)},<{_join(MAX_SUPPORTED_EXCLUSIVE)}",
            ),
            None,
        )
    return ProviderProbe(ProbeState.AVAILABLE, version=text), GraphifyInstall(executable, text)


def _join(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)
