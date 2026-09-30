"""Multi-machine reproducibility (AI Bootstrap P8, task 924dc8a6).

`scan_committed_files` checks that the shared, committed AI configuration
carries no absolute path and no secret-shaped text. `rebuild` reconstructs a
machine's configuration from the committed manifest alone: it links this
checkout to the project in the machine-local registry (the project<->path
mapping stays on the machine, never in the repository), then runs the
idempotent bundle sync. Offline: no network call.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from studio_contracts.bootstrap import BootstrapDryRunReport
from studio_contracts.local.common import contains_secret_material
from studio_contracts.local.identity import ProfileRef
from studio_workspaces import register_workspace
from studio_workspaces.registration import WorkspaceRegistration

from studio_client.bootstrap import BootstrapError, load_manifest, sync

_SCANNED_PREFIXES = (".agents/", ".claude/", ".codex/", ".opencode/", ".studio/")
_SCANNED_FILES = frozenset({"AGENTS.md", "CLAUDE.md", ".mcp.json", "opencode.json"})
_MAX_BYTES = 1_000_000
_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\|/(?!/))|(?<![\w.~-])/(?:home|Users|root)/[^\s/\"'`]+"
)


@dataclass(frozen=True)
class ScanIssue:
    path: str
    line: int
    kind: str  # "absolute_path" | "secret"


@dataclass(frozen=True)
class RebuildResult:
    registration: WorkspaceRegistration
    report: BootstrapDryRunReport
    written: list[str]
    issues: list[ScanIssue] = field(default_factory=list)


def _tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BootstrapError(f"{root} is not a readable Git checkout") from exc
    return [name for name in out.decode("utf-8").split("\0") if name]


def _in_scope(name: str) -> bool:
    return name in _SCANNED_FILES or name.startswith(_SCANNED_PREFIXES)


def scan_committed_files(repo_root: Path | str) -> list[ScanIssue]:
    """Absolute paths and secret-shaped text in the committed shared AI
    configuration. Only Git-tracked files are read; content is never echoed."""
    root = Path(repo_root)
    issues: list[ScanIssue] = []
    for name in sorted(filter(_in_scope, _tracked_files(root))):
        target = root / name
        try:
            if not target.is_file() or target.stat().st_size > _MAX_BYTES:
                continue
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if _ABSOLUTE_PATH.search(line):
                issues.append(ScanIssue(name, number, "absolute_path"))
            if contains_secret_material(line):
                issues.append(ScanIssue(name, number, "secret"))
    return issues


def rebuild(
    repo_root: Path | str,
    registry_dir: Path,
    profile: ProfileRef,
    project_id: UUID,
    *,
    confirm: bool = False,
) -> RebuildResult:
    """Reconstruct this machine's configuration from the committed manifest.
    Refuses when the shared files are unclean, so a leak is never propagated."""
    root = Path(repo_root)
    manifest = load_manifest(root)
    issues = scan_committed_files(root)
    if issues:
        first = issues[0]
        raise BootstrapError(
            f"committed files are not clean ({len(issues)} issue(s), "
            f"e.g. {first.kind} at {first.path}:{first.line}); run `bootstrap scan`"
        )
    registration = register_workspace(
        registry_dir,
        profile,
        project_id,
        str(root.resolve()),
        project_slug=manifest.project.slug,
    )
    report, written = sync(root, manifest, confirm=confirm)
    return RebuildResult(registration, report, written, issues)
