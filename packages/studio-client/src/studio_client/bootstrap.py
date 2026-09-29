"""Local project bundle generator (AI Bootstrap P3, task c691ac49).

Offline-first: the bundle is assembled from the canonical `.agents/` sources
(`build_offline_resolved`) and projected through the local adapters, then
observed against the working tree and materialized with backups. The manifest
(`.agents/bootstrap.json`, `studio.bootstrap/v1`) fixes the target harnesses and
the generation policy; the dry-run report conforms to the P1 contract
(`BootstrapDryRunReport`).

No network, no resolution engine: `resolve_full` stays the only
version-truthful path (DEC-0144). A second run of `sync` writes nothing.
"""

from __future__ import annotations

import difflib
import hashlib
import json
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
    build_offline_resolved,
    canonical_agent_keys,
    canonical_rule_keys,
    load_rule_meta,
    render_agents_rules_block,
    render_claude_rule,
)

MANIFEST_RELATIVE_PATH = ".agents/bootstrap.json"
AGENTS_MD_PATH = "AGENTS.md"
BACKUP_RELATIVE_DIR = ".studio-os/backups/bootstrap"
_RULE_DIR = ".claude/rules"
HASH_PREFIX = "sha256:"


class BootstrapError(RuntimeError):
    """Local bundle generation failure (missing manifest, projection, conflict)."""


@dataclass(frozen=True)
class PlannedFile:
    """One expected output. `block` marks a managed block merged into an
    existing file (`AGENTS.md`) rather than a whole-file artifact."""

    path: str
    content: str
    kind: str
    block: bool = False


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
    then rule projections, then the `AGENTS.md` managed block."""
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
            expected = _merge_block(current, item.content)
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
    replaced file. Conflicting or needs-confirmation reports are refused."""
    root = Path(repo_root)
    planned = planned if planned is not None else plan_files(root, manifest)
    if any(conflict.blocking for conflict in report.conflicts):
        codes = ", ".join(sorted({c.code.value for c in report.conflicts}))
        raise BootstrapError(f"sync blocked by conflicts: {codes}")
    if report.needs_confirmation and not confirm:
        raise BootstrapError("policy 'ask': explicit confirmation required (pass confirm=True)")
    by_path = {item.path: item for item in planned}
    backup_root = root / Path(*BACKUP_RELATIVE_DIR.split("/")) / _timestamp()
    written: list[str] = []
    for observed in report.files:
        if observed.state is BootstrapFileState.UP_TO_DATE:
            continue
        item = by_path[observed.path]
        target = _safe_target(root, item.path)
        if target.exists():
            _backup(root, item.path, backup_root)
        if item.block:
            existing = target.read_text(encoding="utf-8") if target.is_file() else ""
            _write_text(target, _merge_block(existing, item.content))
        else:
            _write_text(target, item.content)
        written.append(item.path)
    return written


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
        if AGENTS_BEGIN_MARKER in text and AGENTS_END_MARKER in text:
            return BootstrapFileState.MODIFIED
        return BootstrapFileState.ABSENT
    if not target.is_file():
        return BootstrapFileState.ABSENT
    if _normalize(target.read_text(encoding="utf-8")) == _normalize(item.content):
        return BootstrapFileState.UP_TO_DATE
    return BootstrapFileState.MODIFIED


def _merge_block(existing: str, block: str) -> str:
    existing = _normalize(existing)
    expected = _normalize(block)
    if AGENTS_BEGIN_MARKER in existing and AGENTS_END_MARKER in existing:
        start = existing.index(AGENTS_BEGIN_MARKER)
        end = existing.index(AGENTS_END_MARKER) + len(AGENTS_END_MARKER)
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


def _backup(root: Path, relative: str, backup_root: Path) -> Path:
    destination = backup_root / Path(*relative.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_target(root, relative), destination)
    return destination


def _write_text(path: Path, text: str, *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise BootstrapError(f"refusing to overwrite existing {path}")
    tmp = path.parent / f".{path.name}.studio-tmp"
    try:
        tmp.write_text(text, encoding="utf-8")
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
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
