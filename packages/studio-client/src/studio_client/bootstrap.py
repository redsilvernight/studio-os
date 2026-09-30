"""Local project bundle generator (AI Bootstrap P3, task c691ac49).

Offline-first: the bundle is assembled from the canonical `.agents/` sources
(`build_offline_resolved`) and projected through the local adapters, then
observed against the working tree and materialized with backups. The manifest
(`.agents/bootstrap.json`, `studio.bootstrap/v1`) fixes the target harnesses and
the generation policy; the dry-run report conforms to the P1 contract
(`BootstrapDryRunReport`).

No network, no resolution engine: `resolve_full` stays the only
version-truthful path (DEC-0144). A second run of `sync` writes nothing, and
`rollback` restores the exact state before the last `sync` from its journal.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from studio_contracts.bootstrap import (
    BootstrapDryRunReport,
    BootstrapFileReport,
    BootstrapFileState,
    BootstrapHarnessRef,
    BootstrapManifest,
    BootstrapPolicy,
    OnModified,
    bootstrap_manifest_problems,
    build_dry_run_report,
)
from studio_contracts.initialization import InitializationProjectSpec

from studio_client.adapters import AdapterError, get_adapter
from studio_client.canonical import (
    AGENTS_BEGIN_MARKER,
    AGENTS_END_MARKER,
    CLAUDE_BEGIN_MARKER,
    CLAUDE_END_MARKER,
    build_offline_resolved,
    canonical_agent_keys,
    canonical_rule_keys,
    load_rule_meta,
    render_agents_rules_block,
    render_claude_md_block,
    render_claude_rule,
)

MANIFEST_RELATIVE_PATH = ".agents/bootstrap.json"
AGENTS_MD_PATH = "AGENTS.md"
CLAUDE_MD_PATH = "CLAUDE.md"
BACKUP_RELATIVE_DIR = ".studio-os/backups/bootstrap"
JOURNAL_NAME = "journal.json"
JOURNAL_SCHEMA_VERSION = 1
_RULE_DIR = ".claude/rules"
HASH_PREFIX = "sha256:"


class BootstrapError(RuntimeError):
    """Local bundle generation failure (missing manifest, projection, conflict)."""


@dataclass(frozen=True)
class PlannedFile:
    """One expected output. `block` marks a managed block merged into an
    existing file (`AGENTS.md`, `CLAUDE.md`) rather than a whole-file artifact."""

    path: str
    content: str
    kind: str
    block: bool = False

    @property
    def markers(self) -> tuple[str, str]:
        if self.path == CLAUDE_MD_PATH:
            return CLAUDE_BEGIN_MARKER, CLAUDE_END_MARKER
        return AGENTS_BEGIN_MARKER, AGENTS_END_MARKER


@dataclass(frozen=True)
class BackupEntry:
    """One file a `sync` run touched: `created` (delete to undo) or `replaced`
    (restore `backup` to undo). `after_label` is the label of what the run
    wrote, used to detect a later edit before rolling back."""

    path: str
    action: str
    backup: str | None
    after_label: str


@dataclass(frozen=True)
class BackupJournal:
    """The record of one `sync` run, stored beside its backups. `status` moves
    from `applied` to `rolled_back` so the same run is never undone twice."""

    directory: Path
    created_at: str
    status: str
    entries: list[BackupEntry]


def manifest_path(repo_root: Path | str) -> Path:
    return Path(repo_root) / Path(*MANIFEST_RELATIVE_PATH.split("/"))


def make_manifest(
    project_slug: str,
    project_name: str,
    harnesses: list[str],
    *,
    description: str | None = None,
    on_modified: OnModified = OnModified.REFUSE,
) -> BootstrapManifest:
    return BootstrapManifest(
        project=InitializationProjectSpec(
            slug=project_slug, name=project_name, description=description
        ),
        harnesses=[BootstrapHarnessRef(id=harness) for harness in harnesses],
        policy=BootstrapPolicy(on_modified=on_modified),
    )


def load_manifest(repo_root: Path | str) -> BootstrapManifest:
    path = manifest_path(repo_root)
    if not path.is_file():
        raise BootstrapError(
            f"no manifest at {MANIFEST_RELATIVE_PATH}; run `studio-client bootstrap init` first"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"cannot read {MANIFEST_RELATIVE_PATH}: {exc}") from exc
    try:
        manifest = BootstrapManifest.model_validate(data)
    except ValueError as exc:
        raise BootstrapError(f"invalid {MANIFEST_RELATIVE_PATH}: {exc}") from exc
    problems = bootstrap_manifest_problems(manifest)
    if problems:
        rendered = ", ".join(f"{p.code.value}:{p.key}" for p in problems)
        raise BootstrapError(f"inconsistent {MANIFEST_RELATIVE_PATH}: {rendered}")
    return manifest


def write_manifest(
    repo_root: Path | str, manifest: BootstrapManifest, *, overwrite: bool = False
) -> Path:
    path = manifest_path(repo_root)
    text = json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    _write_text(path, text, overwrite=overwrite)
    return path


def plan_files(repo_root: Path | str, manifest: BootstrapManifest) -> list[PlannedFile]:
    """Deterministic expected output: agent projections per targeted harness,
    then rule projections, then the `AGENTS.md` and `CLAUDE.md` managed blocks."""
    root = Path(repo_root)
    files: list[PlannedFile] = []
    agent_keys = canonical_agent_keys(root)
    for ref in manifest.harnesses:
        try:
            adapter = get_adapter(ref.id)
        except AdapterError as exc:
            raise BootstrapError(f"harness {ref.id!r} has no local adapter: {exc.message}") from exc
        for key in agent_keys:
            try:
                result = adapter.translate(build_offline_resolved(root, key))
            except (AdapterError, ValueError, OSError) as exc:
                raise BootstrapError(f"cannot project agent {key!r} to {ref.id!r}: {exc}") from exc
            for artifact in result.artifacts:
                files.append(
                    PlannedFile(
                        path=artifact.path.replace("\\", "/"),
                        content=artifact.content,
                        kind="agent",
                    )
                )
    for key in canonical_rule_keys(root):
        applies_to, body = load_rule_meta(root, key)
        files.append(
            PlannedFile(
                path=f"{_RULE_DIR}/{key}.md",
                content=render_claude_rule(key, applies_to, body),
                kind="rule",
            )
        )
    files.append(
        PlannedFile(
            path=AGENTS_MD_PATH, content=render_agents_rules_block(root), kind="block", block=True
        )
    )
    files.append(
        PlannedFile(
            path=CLAUDE_MD_PATH, content=render_claude_md_block(root), kind="block", block=True
        )
    )
    return files


def observe(
    repo_root: Path | str,
    manifest: BootstrapManifest,
    *,
    planned: list[PlannedFile] | None = None,
) -> BootstrapDryRunReport:
    """Read-only: the current state of every planned file as a P1 report."""
    root = Path(repo_root)
    planned = planned if planned is not None else plan_files(root, manifest)
    reports: list[BootstrapFileReport] = []
    for item in planned:
        state = _observe_state(root, item)
        if state is BootstrapFileState.ABSENT:
            reports.append(BootstrapFileReport(path=item.path, state=state))
        else:
            reports.append(
                BootstrapFileReport(
                    path=item.path, state=state, origin_version=1, content_hash=_label(item.content)
                )
            )
    return build_dry_run_report(manifest, reports)


def diff_text(
    repo_root: Path | str,
    manifest: BootstrapManifest,
    *,
    planned: list[PlannedFile] | None = None,
) -> str:
    root = Path(repo_root)
    planned = planned if planned is not None else plan_files(root, manifest)
    chunks: list[str] = []
    for item in planned:
        target = _target(root, item.path)
        current = _normalize(target.read_text(encoding="utf-8")) if target.is_file() else ""
        expected = _normalize(item.content)
        if item.block:
            if expected.rstrip("\n") in current:
                continue
            expected = _merge_block(current, item.content, item.markers)
        elif current == expected:
            continue
        chunks.append(
            "\n".join(
                difflib.unified_diff(
                    current.splitlines(),
                    expected.splitlines(),
                    fromfile=f"a/{item.path}",
                    tofile=f"b/{item.path}",
                    lineterm="",
                )
            )
        )
    return "\n".join(chunk for chunk in chunks if chunk)


def apply_files(
    repo_root: Path | str,
    manifest: BootstrapManifest,
    report: BootstrapDryRunReport,
    *,
    planned: list[PlannedFile] | None = None,
    confirm: bool = False,
) -> list[str]:
    """Write only the files whose state is not `up_to_date`, backing up every
    replaced file and recording a journal so the run can be rolled back.
    Conflicting or needs-confirmation reports are refused."""
    root = Path(repo_root)
    planned = planned if planned is not None else plan_files(root, manifest)
    if any(conflict.blocking for conflict in report.conflicts):
        codes = ", ".join(sorted({c.code.value for c in report.conflicts}))
        raise BootstrapError(f"sync blocked by conflicts: {codes}")
    if report.needs_confirmation and not confirm:
        raise BootstrapError("policy 'ask': explicit confirmation required (pass confirm=True)")
    by_path = {item.path: item for item in planned}
    pending = [f for f in report.files if f.state is not BootstrapFileState.UP_TO_DATE]
    if not pending:
        return []
    backup_root = root / Path(*BACKUP_RELATIVE_DIR.split("/")) / _timestamp()
    written: list[str] = []
    entries: list[BackupEntry] = []
    for observed in pending:
        item = by_path[observed.path]
        target = _safe_target(root, item.path)
        replaced = target.exists()
        if replaced:
            _backup(root, item.path, backup_root)
        if item.block:
            existing = target.read_text(encoding="utf-8") if target.is_file() else ""
            content = _merge_block(existing, item.content, item.markers)
        else:
            content = item.content
        _write_text(target, content)
        entries.append(
            BackupEntry(
                path=item.path,
                action="replaced" if replaced else "created",
                backup=item.path if replaced else None,
                after_label=_label(content),
            )
        )
        written.append(item.path)
    _write_journal(backup_root, entries)
    return written


def rollback(
    repo_root: Path | str,
    *,
    backup_id: str | None = None,
    force: bool = False,
) -> list[str]:
    """Undo a previous `sync`: restore every replaced file byte for byte and
    delete every created file. Refuses when a file changed since that run
    (unless `force`), so a local edit is never clobbered silently. Validation
    runs over every entry before anything is written, so a refusal leaves the
    working tree untouched. The journal is marked `rolled_back`, making a second
    rollback of the same run an explicit error."""
    root = Path(repo_root)
    journal = _read_journal(_find_backup_dir(root, backup_id))
    if journal.status == "rolled_back":
        raise BootstrapError(f"backup {journal.directory.name} was already rolled back")
    planned: list[tuple[str, Path, BackupEntry]] = []
    for entry in journal.entries:
        target = _safe_target(root, entry.path)
        _check_rollback_entry(journal.directory, target, entry, force=force)
        planned.append((entry.path, target, entry))
    undone: list[str] = []
    for path, target, entry in planned:
        if entry.action == "created":
            if target.exists():
                target.unlink()
                undone.append(path)
        else:
            if entry.backup is None:
                raise BootstrapError(f"backup file missing for {entry.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(journal.directory / Path(*entry.backup.split("/")), target)
            undone.append(path)
    _write_journal(
        journal.directory, journal.entries, status="rolled_back", created_at=journal.created_at
    )
    return undone


def list_backups(repo_root: Path | str) -> list[BackupJournal]:
    """Every readable sync journal under the backup directory, newest first."""
    journals: list[BackupJournal] = []
    for directory in _backup_dirs(Path(repo_root)):
        try:
            journals.append(_read_journal(directory))
        except BootstrapError:
            continue
    return journals


def sync(
    repo_root: Path | str, manifest: BootstrapManifest, *, confirm: bool = False
) -> tuple[BootstrapDryRunReport, list[str]]:
    root = Path(repo_root)
    planned = plan_files(root, manifest)
    report = observe(root, manifest, planned=planned)
    written = apply_files(root, manifest, report, planned=planned, confirm=confirm)
    return report, written


def _observe_state(root: Path, item: PlannedFile) -> BootstrapFileState:
    target = _target(root, item.path)
    if item.block:
        if not target.is_file():
            return BootstrapFileState.ABSENT
        text = _normalize(target.read_text(encoding="utf-8"))
        if _normalize(item.content).rstrip("\n") in text:
            return BootstrapFileState.UP_TO_DATE
        begin, end = item.markers
        if begin in text and end in text:
            return BootstrapFileState.MODIFIED
        return BootstrapFileState.ABSENT
    if not target.is_file():
        return BootstrapFileState.ABSENT
    if _normalize(target.read_text(encoding="utf-8")) == _normalize(item.content):
        return BootstrapFileState.UP_TO_DATE
    return BootstrapFileState.MODIFIED


def _merge_block(existing: str, block: str, markers: tuple[str, str]) -> str:
    begin, end_marker = markers
    existing = _normalize(existing)
    expected = _normalize(block)
    if (begin in existing) != (end_marker in existing):
        raise BootstrapError(f"unbalanced managed block markers ({begin}); fix the file by hand")
    if begin in existing:
        start = existing.index(begin)
        end = existing.index(end_marker) + len(end_marker)
        tail = existing[end:]
        if tail.startswith("\n"):
            tail = tail[1:]
        merged = existing[:start] + expected + tail
        return merged if merged.endswith("\n") else merged + "\n"
    if existing and not existing.endswith("\n"):
        existing += "\n"
    separator = "\n" if existing.strip() else ""
    return existing + separator + expected


def _target(root: Path, relative: str) -> Path:
    return root / Path(*relative.split("/"))


def _safe_target(root: Path, relative: str) -> Path:
    """A write target confined to the repository: a symlinked parent that
    escapes the root is refused, never followed."""
    target = _target(root, relative)
    probe = target if target.exists() else target.parent
    try:
        probe.resolve().relative_to(root.resolve())
    except ValueError:
        raise BootstrapError(f"refusing to write outside the repository: {relative}") from None
    return target


def backup_root_for(root: Path) -> Path:
    return root / Path(*BACKUP_RELATIVE_DIR.split("/")) / _timestamp()


def backup_file(root: Path, relative: str, backup_root: Path) -> Path:
    return _backup(root, relative, backup_root)


def _backup(root: Path, relative: str, backup_root: Path) -> Path:
    destination = backup_root / Path(*relative.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_target(root, relative), destination)
    return destination


def _backup_dirs(root: Path) -> list[Path]:
    base = root / Path(*BACKUP_RELATIVE_DIR.split("/"))
    if not base.is_dir():
        return []
    return sorted(
        (child for child in base.iterdir() if child.is_dir()),
        key=lambda child: child.name,
        reverse=True,
    )


def _find_backup_dir(root: Path, backup_id: str | None) -> Path:
    if backup_id is not None and ("/" in backup_id or "\\" in backup_id or ".." in backup_id):
        raise BootstrapError(f"invalid backup id {backup_id!r}")
    directories = _backup_dirs(root)
    if backup_id is not None:
        for directory in directories:
            if directory.name == backup_id:
                return directory
        raise BootstrapError(f"no bootstrap backup with id {backup_id!r}")
    for directory in directories:
        if (directory / JOURNAL_NAME).is_file():
            return directory
    raise BootstrapError(
        "no bootstrap backup to roll back; run `studio-client bootstrap sync` first"
    )


def _write_journal(
    directory: Path,
    entries: list[BackupEntry],
    *,
    status: str = "applied",
    created_at: str | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "status": status,
        "entries": [
            {
                "path": entry.path,
                "action": entry.action,
                "backup": entry.backup,
                "after_label": entry.after_label,
            }
            for entry in entries
        ],
    }
    (directory / JOURNAL_NAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _read_journal(directory: Path) -> BackupJournal:
    path = directory / JOURNAL_NAME
    if not path.is_file():
        raise BootstrapError(f"backup {directory.name} has no journal; cannot roll back")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"cannot read backup journal {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != JOURNAL_SCHEMA_VERSION:
        raise BootstrapError(f"unsupported backup journal in {directory.name}")
    rows = data.get("entries")
    if not isinstance(rows, list):
        raise BootstrapError(f"malformed backup journal in {directory.name}")
    try:
        entries = [
            BackupEntry(
                path=str(row["path"]),
                action=str(row["action"]),
                backup=str(row["backup"]) if row.get("backup") is not None else None,
                after_label=str(row["after_label"]),
            )
            for row in rows
        ]
    except (KeyError, TypeError, AttributeError) as exc:
        raise BootstrapError(f"malformed backup journal in {directory.name}") from exc
    return BackupJournal(
        directory=directory,
        created_at=str(data.get("created_at", "")),
        status=str(data.get("status", "applied")),
        entries=entries,
    )


def _check_rollback_entry(
    directory: Path, target: Path, entry: BackupEntry, *, force: bool
) -> None:
    if entry.action not in ("created", "replaced"):
        raise BootstrapError(f"unknown rollback action {entry.action!r} for {entry.path}")
    if entry.action == "replaced":
        if entry.backup is None:
            raise BootstrapError(f"backup file missing for {entry.path}")
        backup = directory / Path(*entry.backup.split("/"))
        if not backup.is_file():
            raise BootstrapError(f"backup file missing for {entry.path}")
    if target.exists() and not target.is_file():
        raise BootstrapError(f"refusing to roll back a non-file target: {entry.path}")
    if target.is_file() and not force:
        current = _label(target.read_text(encoding="utf-8"))
        if current != entry.after_label:
            raise BootstrapError(
                f"{entry.path} changed since the backup; refusing to roll back "
                "(pass --force to override)"
            )


def _write_text(path: Path, text: str, *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise BootstrapError(f"refusing to overwrite existing {path}")
    tmp = path.parent / f".{path.name}.studio-tmp"
    try:
        with tmp.open("w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
    except OSError as exc:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise BootstrapError(f"failed writing {path}: {exc}") from exc


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


def _label(content: str) -> str:
    return HASH_PREFIX + hashlib.sha256(_normalize(content).encode("utf-8")).hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
