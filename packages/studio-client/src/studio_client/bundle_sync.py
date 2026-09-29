"""Project AI Bootstrap bundle — init/check/diff/sync (P3).

The bundle is the complete local projection of a project's AI integration:
rules, agent definitions, skills, and the CLAUDE.md managed block. This
module provides deterministic, side-effect-free planning and safe
application with backup/confirmation before any overwrite.

States: current, missing, outdated, locally_modified.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from studio_client.adapters import get_adapter, list_adapters
from studio_client.canonical import (
    build_offline_resolved,
    canonical_agent_keys,
    canonical_rule_keys,
    load_rule_meta,
    render_agents_rules_block,
    render_claude_rule,
)

SyncState = Literal["current", "missing", "outdated", "locally_modified"]

_BUNDLE_SCHEMA_VERSION = 1
_MANAGED_MARKER = "studio-managed"

_CLAUDE_BEGIN = "<!-- BEGIN STUDIO-OS MANAGED -->"
_CLAUDE_END = "<!-- END STUDIO-OS MANAGED -->"


class BundleSyncError(RuntimeError):
    """Base error for invalid or unsafe bundle synchronization."""


class BundleSyncConflictError(BundleSyncError):
    """Raised when a synchronization would overwrite local content."""


@dataclass(frozen=True)
class BundleTargetPlan:
    """Desired state of one bundle file."""

    kind: Literal["rule", "agent", "skill", "claude_md"]
    path: Path
    state: SyncState
    current_text: str | None
    current_sha256: str | None
    desired_text: str
    desired_sha256: str


@dataclass(frozen=True)
class BundlePlanEntry:
    """One bundle file and its desired content."""

    target: BundleTargetPlan


@dataclass(frozen=True)
class BundleSyncPlan:
    """A deterministic, side-effect-free synchronization plan."""

    repo_root: Path
    entries: tuple[BundlePlanEntry, ...]
    manifest_path: Path
    manifest_text: str

    @property
    def current(self) -> tuple[BundleTargetPlan, ...]:
        return self._targets_with_state("current")

    @property
    def missing(self) -> tuple[BundleTargetPlan, ...]:
        return self._targets_with_state("missing")

    @property
    def drifted(self) -> tuple[BundleTargetPlan, ...]:
        return tuple(
            entry.target
            for entry in self.entries
            if entry.target.state in {"outdated", "locally_modified"}
        )

    @property
    def outdated(self) -> tuple[BundleTargetPlan, ...]:
        return self._targets_with_state("outdated")

    @property
    def locally_modified(self) -> tuple[BundleTargetPlan, ...]:
        return self._targets_with_state("locally_modified")

    def _targets_with_state(self, state: SyncState) -> tuple[BundleTargetPlan, ...]:
        return tuple(entry.target for entry in self.entries if entry.target.state == state)


@dataclass(frozen=True)
class BundleSyncResult:
    """Files written and backups created by an applied plan."""

    written: tuple[Path, ...]
    backups: tuple[Path, ...]
    manifest_path: Path


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _load_managed_hashes(manifest_path: Path) -> dict[str, str]:
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != _BUNDLE_SCHEMA_VERSION:
        return {}
    rows = payload.get("files")
    if not isinstance(rows, list):
        return {}
    hashes: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rel_path = row.get("path")
        digest = row.get("sha256")
        if isinstance(rel_path, str) and isinstance(digest, str):
            hashes[rel_path] = digest
    return hashes


def _plan_target(
    repo_root: Path,
    rel_path: str,
    kind: Literal["rule", "agent", "skill", "claude_md"],
    desired_text: str,
    managed_hash: str | None,
) -> BundleTargetPlan:
    path = repo_root / rel_path
    desired_hash = _sha256(desired_text)
    if not path.exists():
        return BundleTargetPlan(kind, path, "missing", None, None, desired_text, desired_hash)
    if not path.is_file():
        raise BundleSyncError(f"bundle target is not a regular file: {path}")
    try:
        current = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BundleSyncError(f"bundle target is not valid UTF-8: {path}") from exc
    current_normalized = _normalize(current)
    desired_normalized = _normalize(desired_text)
    current_hash = _sha256(current_normalized)
    if current_normalized == desired_normalized:
        state: SyncState = "current"
    elif managed_hash is not None and current_hash == managed_hash:
        state = "outdated"
    else:
        state = "locally_modified"
    return BundleTargetPlan(
        kind, path, state, current_normalized, current_hash, desired_text, desired_hash
    )


def _render_claude_md_block(repo_root: Path) -> str:
    """The CLAUDE.md managed block: project identity + protocol reference."""
    lines = [
        _CLAUDE_BEGIN,
        "",
        "# Studi'OS Project Bootstrap",
        "",
        "This project is managed by Studi'OS. The block below is auto-generated.",
        "Do not edit between the markers; use `studio-client bundle sync` instead.",
        "",
        "## Quick Start",
        "",
        "1. Open your AI harness (Claude Code, OpenCode, Codex) in this directory.",
        "2. Call `studio_prepare_context` to load project context.",
        "3. Follow the agent loop: `studio_start_work` → work → `studio_handoff`.",
        "",
        "## Resources",
        "",
        "- Rules: `.claude/rules/` (synced from `.agents/rules/`)",
        "- Agents: `.claude/agents/`, `.opencode/agents/`, `.codex/agents/`",
        "- Skills: `.agents/skills/`, `.claude/skills/`",
        "",
        _CLAUDE_END,
        "",
    ]
    return "\n".join(lines)


def _collect_bundle_files(
    repo_root: Path,
) -> list[tuple[str, Literal["rule", "agent", "skill", "claude_md"], str]]:
    """Collect all bundle files: (relative_path, kind, desired_content)."""
    files: list[tuple[str, Literal["rule", "agent", "skill", "claude_md"], str]] = []

    for key in canonical_rule_keys(repo_root):
        applies_to, body = load_rule_meta(repo_root, key)
        rel_path = f".claude/rules/{key}.md"
        files.append((rel_path, "rule", render_claude_rule(key, applies_to, body)))

    agents_block = render_agents_rules_block(repo_root)
    files.append(("AGENTS.md", "rule", agents_block))

    for adapter_id in list_adapters():
        adapter = get_adapter(adapter_id)
        for key in canonical_agent_keys(repo_root):
            resolved = build_offline_resolved(repo_root, key)
            result = adapter.translate(resolved)
            for artifact in result.artifacts:
                files.append((artifact.path, "agent", artifact.content))

    claude_md = repo_root / "CLAUDE.md"
    if claude_md.exists():
        text = claude_md.read_text(encoding="utf-8")
        pattern = re.compile(
            re.escape(_CLAUDE_BEGIN) + r".*?" + re.escape(_CLAUDE_END),
            re.S,
        )
        if pattern.search(text):
            new_text = pattern.sub(_render_claude_md_block(repo_root).rstrip("\n"), text)
        else:
            new_text = text.rstrip("\n") + "\n\n" + _render_claude_md_block(repo_root)
    else:
        new_text = _render_claude_md_block(repo_root)
    files.append(("CLAUDE.md", "claude_md", new_text))

    return files


def plan_bundle_sync(repo_root: Path | str) -> BundleSyncPlan:
    """Inspect all bundle targets without changing the filesystem."""
    root = Path(repo_root).resolve()
    manifest_path = root / ".studio-os" / "bundle-manifest.json"
    managed_hashes = _load_managed_hashes(manifest_path)

    entries: list[BundlePlanEntry] = []
    for rel_path, kind, desired_text in _collect_bundle_files(root):
        target = _plan_target(root, rel_path, kind, desired_text, managed_hashes.get(rel_path))
        entries.append(BundlePlanEntry(target=target))

    manifest = {
        "schema_version": _BUNDLE_SCHEMA_VERSION,
        "files": [
            {
                "path": entry.target.path.relative_to(root).as_posix(),
                "sha256": entry.target.desired_sha256,
                "kind": entry.target.kind,
            }
            for entry in entries
        ],
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return BundleSyncPlan(
        repo_root=root,
        entries=tuple(entries),
        manifest_path=manifest_path,
        manifest_text=manifest_text,
    )


def diff_bundle_plan(plan: BundleSyncPlan) -> str:
    """Return deterministic unified diffs for missing and drifted targets."""
    chunks: list[str] = []
    for entry in plan.entries:
        target = entry.target
        if target.state == "current":
            continue
        desired_lines = target.desired_text.splitlines(keepends=True)
        rel_path = target.path.relative_to(plan.repo_root).as_posix()
        current_lines = (
            [] if target.current_text is None else target.current_text.splitlines(keepends=True)
        )
        chunks.extend(
            difflib.unified_diff(
                current_lines,
                desired_lines,
                fromfile="/dev/null" if target.state == "missing" else rel_path,
                tofile=rel_path,
                lineterm="\n",
            )
        )
    return "".join(chunks)


def apply_bundle_sync(
    plan: BundleSyncPlan,
    *,
    overwrite: bool = False,
) -> BundleSyncResult:
    """Apply a plan atomically per file, backing up authorized overwrites."""
    conflicts = list(plan.locally_modified)
    if conflicts and not overwrite:
        paths = ", ".join(str(t.path) for t in conflicts)
        raise BundleSyncConflictError(
            f"refusing to overwrite locally modified bundle files without overwrite=True: {paths}"
        )
    _verify_plan_is_fresh(plan)

    backup_root: Path | None = None
    backups: list[Path] = []
    if conflicts:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_root = plan.repo_root / ".studio-os" / "backups" / "bundle" / timestamp
        for entry in plan.entries:
            target = entry.target
            if target.state != "locally_modified" or target.current_text is None:
                continue
            backup_path = backup_root / target.path.relative_to(plan.repo_root)
            _atomic_write(backup_path, target.current_text)
            backups.append(backup_path)

    written: list[Path] = []
    for entry in plan.entries:
        target = entry.target
        if target.state == "current":
            continue
        _atomic_write(target.path, target.desired_text)
        written.append(target.path)
    _atomic_write(plan.manifest_path, plan.manifest_text)
    return BundleSyncResult(
        written=tuple(written),
        backups=tuple(backups),
        manifest_path=plan.manifest_path,
    )


def _verify_plan_is_fresh(plan: BundleSyncPlan) -> None:
    for entry in plan.entries:
        target = entry.target
        if target.path.exists():
            if not target.path.is_file():
                raise BundleSyncConflictError(
                    f"bundle target changed since planning: {target.path}"
                )
            current_hash = _sha256(_normalize(target.path.read_text(encoding="utf-8")))
        else:
            current_hash = None
        if current_hash != target.current_sha256:
            raise BundleSyncConflictError(f"bundle target changed since planning: {target.path}")


def init_bundle(repo_root: Path | str) -> BundleSyncPlan:
    """Initialize the bundle: create manifest and return the plan (no writes)."""
    return plan_bundle_sync(repo_root)


def check_bundle(repo_root: Path | str) -> tuple[BundleSyncPlan, list[str]]:
    """Check the bundle: return (plan, failures). Failures are human-readable."""
    plan = plan_bundle_sync(repo_root)
    failures: list[str] = []
    for entry in plan.entries:
        target = entry.target
        if target.state == "missing":
            failures.append(f"missing: {target.path.relative_to(plan.repo_root).as_posix()}")
        elif target.state == "outdated":
            failures.append(f"outdated: {target.path.relative_to(plan.repo_root).as_posix()}")
        elif target.state == "locally_modified":
            rel = target.path.relative_to(plan.repo_root).as_posix()
            failures.append(f"locally_modified: {rel}")
    return plan, failures
