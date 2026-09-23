from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote

from studio_contracts.local.common import ComponentState

OBSIDIAN_INTEGRATION_ID = "obsidian"
"""Optional Markdown editor integration. Studi'OS never requires it: reading,
indexing and searching the vault work with no editor installed."""

_WINDOWS_SUFFIXES = (
    ("LOCALAPPDATA", "Obsidian", "Obsidian.exe"),
    ("PROGRAMFILES", "Obsidian", "Obsidian.exe"),
    ("PROGRAMFILES(X86)", "Obsidian", "Obsidian.exe"),
)


class OpenVaultOutcome(StrEnum):
    OPENED = "opened"
    NOT_INSTALLED = "not_installed"
    VAULT_MISSING = "vault_missing"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ObsidianProbe:
    """Detection result. Carries a local executable path for the caller's own
    use only — this object never crosses the local protocol boundary."""

    state: ComponentState
    executable: Path | None = None
    registered_vaults: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenVaultResult:
    outcome: OpenVaultOutcome
    state: ComponentState
    launched: bool


def _default_which(name: str) -> str | None:
    return shutil.which(name)


def _candidate_executables(
    platform: str, environ: Mapping[str, str], which: Callable[[str], str | None]
) -> list[Path]:
    candidates: list[Path] = []
    if platform.startswith("win"):
        for variable, *parts in _WINDOWS_SUFFIXES:
            base = environ.get(variable)
            if base:
                candidates.append(Path(base, *parts))
    else:
        candidates.extend([Path("/Applications/Obsidian.app"), Path.home() / ".local/bin/obsidian"])
    found = which("obsidian")
    if found:
        candidates.append(Path(found))
    return candidates


def registered_vault_paths(
    environ: Mapping[str, str] | None = None, platform: str | None = None
) -> tuple[str, ...]:
    """Vaults the editor itself knows about, read-only. A missing or malformed
    configuration simply yields nothing — Studi'OS never writes this file."""
    environment = os.environ if environ is None else environ
    system = sys.platform if platform is None else platform
    if system.startswith("win"):
        base = environment.get("APPDATA")
        if not base:
            return ()
        config = Path(base) / "obsidian" / "obsidian.json"
    else:
        config = Path.home() / "Library/Application Support/obsidian/obsidian.json"
        if not config.is_file():
            config = Path.home() / ".config/obsidian/obsidian.json"
    if not config.is_file():
        return ()
    try:
        parsed = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ()
    vaults = parsed.get("vaults") if isinstance(parsed, dict) else None
    if not isinstance(vaults, dict):
        return ()
    paths: list[str] = []
    for entry in vaults.values():
        if isinstance(entry, dict):
            candidate = entry.get("path")
            if isinstance(candidate, str) and candidate:
                paths.append(candidate)
    return tuple(sorted(paths))


def detect_obsidian(
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    which: Callable[[str], str | None] | None = None,
) -> ObsidianProbe:
    environment = os.environ if environ is None else environ
    system = sys.platform if platform is None else platform
    resolver = which or _default_which
    for candidate in _candidate_executables(system, environment, resolver):
        try:
            if candidate.is_file():
                return ObsidianProbe(
                    state=ComponentState.READY,
                    executable=candidate,
                    registered_vaults=registered_vault_paths(environment, system),
                )
        except OSError:
            continue
    return ObsidianProbe(
        state=ComponentState.NOT_INSTALLED,
        executable=None,
        registered_vaults=registered_vault_paths(environment, system),
    )


def vault_uri(root: Path) -> str:
    return f"obsidian://open?path={quote(str(root.resolve()))}"


def _default_opener(uri: str) -> None:
    if sys.platform.startswith("win"):
        starter = getattr(os, "startfile", None)
        if starter is not None:
            starter(uri)
            return
    command = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen(
        [command, uri],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def open_vault_in_obsidian(
    root: Path,
    *,
    probe: ObsidianProbe | None = None,
    opener: Callable[[str], None] | None = None,
) -> OpenVaultResult:
    """Open the vault in the editor through a single bounded primitive: one
    URI handed to the platform opener. No configuration is written, no file is
    modified, and nothing happens at all when the editor is absent."""
    observed = probe or detect_obsidian()
    if observed.state is not ComponentState.READY:
        return OpenVaultResult(
            outcome=OpenVaultOutcome.NOT_INSTALLED, state=observed.state, launched=False
        )
    if not root.is_dir():
        return OpenVaultResult(
            outcome=OpenVaultOutcome.VAULT_MISSING,
            state=ComponentState.UNAVAILABLE,
            launched=False,
        )
    launcher = opener or _default_opener
    try:
        launcher(vault_uri(root))
    except OSError:
        return OpenVaultResult(
            outcome=OpenVaultOutcome.UNAVAILABLE, state=ComponentState.UNAVAILABLE, launched=False
        )
    return OpenVaultResult(
        outcome=OpenVaultOutcome.OPENED, state=ComponentState.READY, launched=True
    )
