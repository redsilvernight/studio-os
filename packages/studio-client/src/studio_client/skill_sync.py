"""Project effective Studio Library skills into global harness directories."""

from __future__ import annotations

import difflib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from studio_contracts.library import skill_file_path_error

from studio_client.context.library import LibraryContextItem, LibraryContextProvider
from studio_client.drift import SyncState, classify_state
from studio_client.projection_backups import (
    ProjectionBackup,
    commit_projection_backup,
    prepare_projection_backup,
)

_STABLE_KEY_RE = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,199}\Z")
_MANIFEST_SCHEMA_VERSION = 1
OPENCODE_SECTION_HEADING = "## Spécificités OpenCode"
_OPENCODE_SKILLS_DIR = (".config", "opencode", "skills")
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
GLOBAL_PROJECTION_SCOPES = frozenset({"studio", "user"})


class SkillSyncError(RuntimeError):
    """Base error for invalid or unsafe skill synchronization."""


class SkillSyncConflictError(SkillSyncError):
    """Raised when a synchronization would overwrite local content."""


@dataclass(frozen=True)
class SkillTargetPlan:
    """Desired state of one harness copy of a skill."""

    harness: Literal["agents", "claude", "opencode"]
    path: Path
    state: SyncState
    current_text: str | None
    current_sha256: str | None
    desired_text: str | None = None
    rel: str | None = None
    """Path relative to the skill directory for an auxiliary file (None = SKILL.md)."""


@dataclass(frozen=True)
class SkillPlanEntry:
    """Rendered skill and the harness destinations that consume it.

    ``targets`` keeps the two historical destinations; ``opencode`` is only set
    when the plan was built with ``include_opencode=True``."""

    projection: LibraryContextItem
    rendered: str
    sha256: str
    targets: tuple[SkillTargetPlan, SkillTargetPlan]
    opencode: SkillTargetPlan | None = None
    aux: tuple[SkillTargetPlan, ...] = ()
    """Auxiliary files of a multi-file skill, one per harness copy."""
    aux_hashes: tuple[tuple[str, str], ...] = ()
    """(relative path, sha256) of every auxiliary file, recorded in the manifest."""

    @property
    def all_targets(self) -> tuple[SkillTargetPlan, ...]:
        if self.opencode is None:
            return self.targets
        return (*self.targets, self.opencode)

    @property
    def all_files(self) -> tuple[SkillTargetPlan, ...]:
        return (*self.all_targets, *self.aux)


@dataclass(frozen=True)
class SkillSyncPlan:
    """A deterministic, side-effect-free synchronization plan."""

    home: Path
    entries: tuple[SkillPlanEntry, ...]
    manifest_path: Path
    manifest_text: str
    retired: tuple[SkillTargetPlan, ...] = ()
    manifest_before: str | None = None
    """Unmodified managed copies of deprecated skills, removed on apply."""

    @property
    def current(self) -> tuple[SkillTargetPlan, ...]:
        return self._targets_with_state("current")

    @property
    def missing(self) -> tuple[SkillTargetPlan, ...]:
        return self._targets_with_state("missing")

    @property
    def drifted(self) -> tuple[SkillTargetPlan, ...]:
        return tuple(
            target
            for entry in self.entries
            for target in entry.all_files
            if target.state in {"outdated", "locally_modified"}
        )

    @property
    def outdated(self) -> tuple[SkillTargetPlan, ...]:
        return self._targets_with_state("outdated")

    @property
    def locally_modified(self) -> tuple[SkillTargetPlan, ...]:
        return self._targets_with_state("locally_modified")

    def _targets_with_state(self, state: SyncState) -> tuple[SkillTargetPlan, ...]:
        return tuple(
            target for entry in self.entries for target in entry.all_files if target.state == state
        )


@dataclass(frozen=True)
class SkillSyncResult:
    """Files written and backups created by an applied plan."""

    written: tuple[Path, ...]
    backups: tuple[Path, ...]
    manifest_path: Path
    removed: tuple[Path, ...] = ()
    conflicts: tuple[Path, ...] = ()
    """Locally modified targets left untouched (only when ``overwrite`` is False)."""


async def fetch_skill_projections(
    api: Any,
    project_id: UUID | None,
    limit: int = 500,
) -> tuple[LibraryContextItem, ...]:
    """Fetch effective skills visible to the caller for global projection.

    Deprecated rows are kept so ``plan_skill_sync`` can retire their managed copies."""

    result = await LibraryContextProvider(api).fetch(
        project_id,
        limit=limit,
        kinds=("skill",),
    )
    return tuple(
        sorted(
            (item for item in result.items if item.scope in GLOBAL_PROJECTION_SCOPES),
            key=lambda item: item.stable_key,
        )
    )


def render_skill(projection: LibraryContextItem, *, allow_project: bool = False) -> str:
    """Render a Library skill as a harness-compatible ``SKILL.md``."""

    _validate_projection(projection, allow_project=allow_project)
    description = " ".join((projection.description or "").split())
    if not description:
        description = " ".join(projection.title.split())
    body = projection.text.replace("\r\n", "\n").replace("\r", "\n").strip()
    provenance = (
        "<!-- studio-os-library: "
        f"stable_key={projection.stable_key}; version={projection.version}; "
        f"version_origin={projection.version_origin}; scope={projection.scope} -->"
    )
    rendered = (
        "---\n"
        f"name: {json.dumps(projection.stable_key, ensure_ascii=False)}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "---\n\n"
        f"{provenance}\n"
    )
    if body:
        rendered += f"\n{body}\n"
    return rendered


def plan_skill_sync(
    home: Path | str,
    projections: Sequence[LibraryContextItem],
    *,
    include_opencode: bool = False,
    allow_project: bool = False,
) -> SkillSyncPlan:
    """Inspect global skill targets without changing the filesystem.

    Deprecated projections are never projected; their unmodified managed copies
    are listed in ``retired`` and removed on apply."""

    root = Path(home).expanduser().resolve()
    manifest_path = root / ".studio-os" / "library-skills-manifest.json"
    manifest_before = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else None
    managed_hashes = _load_managed_hashes(manifest_path)
    opencode_hashes = _load_managed_hashes(manifest_path, target="opencode")
    managed_files = _load_managed_files(manifest_path)
    entries: list[SkillPlanEntry] = []
    retired: list[SkillTargetPlan] = []
    seen: set[str] = set()
    for projection in sorted(projections, key=lambda item: item.stable_key):
        _validate_projection(projection, allow_project=allow_project)
        if projection.stable_key in seen:
            raise SkillSyncError(f"duplicate skill stable_key: {projection.stable_key!r}")
        seen.add(projection.stable_key)
        rendered = render_skill(projection, allow_project=allow_project)
        _validate_files(projection.files)
        previous_files = managed_files.get(projection.stable_key, {})
        if projection.deprecated:
            retired.extend(
                _plan_removed_files(
                    root,
                    projection.stable_key,
                    previous_files,
                    frozenset(),
                    include_opencode=include_opencode,
                )
            )
            retired.extend(
                _plan_retired_targets(
                    root,
                    projection.stable_key,
                    rendered,
                    managed_hashes.get(projection.stable_key),
                    opencode_hashes.get(projection.stable_key) if include_opencode else None,
                    include_opencode=include_opencode,
                )
            )
            continue
        desired_hash = _sha256(rendered)
        targets = (
            _plan_target(
                root,
                projection.stable_key,
                "agents",
                rendered,
                managed_hashes.get(projection.stable_key),
            ),
            _plan_target(
                root,
                projection.stable_key,
                "claude",
                rendered,
                managed_hashes.get(projection.stable_key),
            ),
        )
        opencode = (
            _plan_opencode_target(
                root,
                projection.stable_key,
                rendered,
                opencode_hashes.get(projection.stable_key),
            )
            if include_opencode
            else None
        )
        aux = _plan_aux_targets(
            root,
            projection.stable_key,
            projection.files,
            previous_files,
            include_opencode=include_opencode,
        )
        retired.extend(
            _plan_removed_files(
                root,
                projection.stable_key,
                previous_files,
                frozenset(path for path, _ in projection.files),
                include_opencode=include_opencode,
            )
        )
        entries.append(
            SkillPlanEntry(
                projection=projection,
                rendered=rendered,
                sha256=desired_hash,
                targets=targets,
                opencode=opencode,
                aux=aux,
                aux_hashes=tuple((path, _sha256(text)) for path, text in projection.files),
            )
        )

    manifest = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "skills": [
            {
                "scope": entry.projection.scope,
                "sha256": entry.sha256,
                "stable_key": entry.projection.stable_key,
                **({"target_sha256": {"opencode": entry.sha256}} if entry.opencode else {}),
                **({"files": dict(entry.aux_hashes)} if entry.aux_hashes else {}),
                "version": entry.projection.version,
                "version_origin": entry.projection.version_origin,
            }
            for entry in entries
        ],
    }
    manifest_text = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return SkillSyncPlan(
        home=root,
        entries=tuple(entries),
        manifest_path=manifest_path,
        manifest_text=manifest_text,
        retired=tuple(retired),
        manifest_before=manifest_before,
    )


def plan_skill_uninstall(
    home: Path | str,
    stable_keys: Sequence[str],
    *,
    include_opencode: bool = True,
) -> SkillSyncPlan:
    """Plan the local removal of managed skills (SKILL.md and auxiliary files).

    Only unmodified copies recorded in the manifest are removed; modified, unmanaged
    or unlisted files stay. The manifest rows of the removed keys are dropped.
    Library data is untouched: this is local uninstall, not deprecation."""

    root = Path(home).expanduser().resolve()
    manifest_path = root / ".studio-os" / "library-skills-manifest.json"
    before = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else None
    payload: dict[str, Any] = (
        json.loads(before) if before else {"schema_version": _MANIFEST_SCHEMA_VERSION}
    )
    rows = [r for r in payload.get("skills", []) if isinstance(r, dict)]
    managed = {r["stable_key"]: r for r in rows if isinstance(r.get("stable_key"), str)}
    managed_hashes = _load_managed_hashes(manifest_path)
    opencode_hashes = _load_managed_hashes(manifest_path, target="opencode")
    managed_files = _load_managed_files(manifest_path)
    retired: list[SkillTargetPlan] = []
    for key in stable_keys:
        if key not in managed:
            raise SkillSyncError(f"skill {key!r} is not managed in this home")
        retired.extend(
            _plan_retired_targets(
                root,
                key,
                None,
                managed_hashes.get(key),
                opencode_hashes.get(key),
                include_opencode=include_opencode,
            )
        )
        retired.extend(
            _plan_removed_files(
                root,
                key,
                managed_files.get(key, {}),
                frozenset(),
                include_opencode=include_opencode,
            )
        )
    payload["skills"] = [r for r in rows if r["stable_key"] not in set(stable_keys)]
    return SkillSyncPlan(
        home=root,
        entries=(),
        manifest_path=manifest_path,
        manifest_text=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        retired=tuple(retired),
        manifest_before=before,
    )


def diff_skill_plan(plan: SkillSyncPlan) -> str:
    """Return deterministic unified diffs for missing and drifted targets."""

    chunks: list[str] = []
    for entry in plan.entries:
        seen: set[tuple[str | None, str]] = set()
        for target in entry.all_files:
            if target.state == "current":
                continue
            desired = _desired_text(entry, target)
            if target.state != "missing":
                if (target.current_text, desired) in seen:
                    continue
                seen.add((target.current_text, desired))
            desired_lines = desired.splitlines(keepends=True)
            relative = target.path.relative_to(plan.home).as_posix()
            current_lines = (
                [] if target.current_text is None else target.current_text.splitlines(keepends=True)
            )
            chunks.extend(
                difflib.unified_diff(
                    current_lines,
                    desired_lines,
                    fromfile="/dev/null" if target.state == "missing" else relative,
                    tofile=relative,
                    lineterm="\n",
                )
            )
    return "".join(chunks)


def apply_skill_sync(
    plan: SkillSyncPlan,
    *,
    overwrite: bool = False,
    selected_keys: set[str] | None = None,
    journal_sink: list[ProjectionBackup] | None = None,
) -> SkillSyncResult:
    """Apply a plan atomically per file, backing up authorized overwrites."""

    if selected_keys is not None:
        known = {entry.projection.stable_key for entry in plan.entries}
        if selected_keys - known:
            raise SkillSyncError("unknown skill selection")
        if not selected_keys:
            return SkillSyncResult(
                written=(), backups=(), manifest_path=plan.manifest_path, removed=()
            )
        manifest = json.loads(plan.manifest_text)
        previous_text = (
            plan.manifest_path.read_text(encoding="utf-8") if plan.manifest_path.is_file() else None
        )
        previous = json.loads(previous_text) if previous_text is not None else {}
        if not isinstance(previous, dict) or not isinstance(previous.get("skills", []), list):
            raise SkillSyncError("invalid existing skill manifest")
        manifest["skills"] = [
            row
            for row in previous.get("skills", [])
            if isinstance(row, dict) and row.get("stable_key") not in selected_keys
        ] + [row for row in manifest["skills"] if row["stable_key"] in selected_keys]
        manifest["skills"].sort(key=lambda row: row["stable_key"])
        plan = replace(
            plan,
            entries=tuple(
                entry for entry in plan.entries if entry.projection.stable_key in selected_keys
            ),
            retired=(),
            manifest_before=previous_text,
            manifest_text=json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    conflicts = tuple(target for target in plan.locally_modified)
    skipped = () if overwrite else conflicts
    skipped_paths = {target.path for target in skipped}
    _verify_plan_is_fresh(plan)

    desired: dict[Path, str | None] = {
        target.path: _desired_text(entry, target)
        for entry in plan.entries
        for target in entry.all_files
        if target.state != "current" and target.path not in skipped_paths
    }
    desired.update({target.path: None for target in plan.retired})
    desired[plan.manifest_path] = plan.manifest_text
    journal = prepare_projection_backup(plan.home, desired)
    _verify_plan_is_fresh(plan)

    backup_root: Path | None = None
    backups: list[Path] = []
    if conflicts and overwrite:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_root = plan.home / ".studio-os" / "backups" / "skills" / timestamp
        for entry in plan.entries:
            for target in entry.all_files:
                if target.state != "locally_modified" or target.current_text is None:
                    continue
                backup_path = _backup_path(
                    backup_root,
                    entry.projection.stable_key,
                    target.harness,
                    target.rel,
                )
                _atomic_write(backup_path, target.current_text)
                backups.append(backup_path)

    written: list[Path] = []
    for entry in plan.entries:
        for target in entry.all_files:
            if target.state == "current" or target.path in skipped_paths:
                continue
            _atomic_write(target.path, _desired_text(entry, target))
            written.append(target.path)
    removed: list[Path] = []
    for target in plan.retired:
        target.path.unlink()
        removed.append(target.path)
        _prune_empty_dirs(target.path.parent, plan.home)
    _atomic_write(plan.manifest_path, plan.manifest_text)
    if journal_sink is None:
        commit_projection_backup(journal)
    elif journal is not None:
        journal_sink.append(journal)
    return SkillSyncResult(
        written=tuple(written),
        backups=tuple(backups),
        manifest_path=plan.manifest_path,
        removed=tuple(removed),
        conflicts=tuple(target.path for target in skipped),
    )


def _validate_projection(projection: LibraryContextItem, *, allow_project: bool = False) -> None:
    key = projection.stable_key
    windows_stem = key.split(".", 1)[0].upper()
    if (
        not _STABLE_KEY_RE.fullmatch(key)
        or key in {".", ".."}
        or ".." in key
        or key.endswith(".")
        or windows_stem in _WINDOWS_RESERVED_NAMES
    ):
        raise SkillSyncError(f"unsafe skill stable_key: {key!r}")
    if projection.library_kind != "skill":
        raise SkillSyncError(f"expected a skill projection, got {projection.library_kind!r}")
    if projection.scope not in GLOBAL_PROJECTION_SCOPES and not (
        allow_project and projection.scope == "project"
    ):
        raise SkillSyncError(
            f"refusing to project non-global skill {key!r} with scope {projection.scope!r}"
        )
    if projection.version <= 0:
        raise SkillSyncError(f"invalid skill version for {key!r}: {projection.version}")


def _desired_text(entry: SkillPlanEntry, target: SkillTargetPlan) -> str:
    return entry.rendered if target.desired_text is None else target.desired_text


def split_opencode_section(text: str) -> tuple[str, str | None]:
    """Split a SKILL.md into its canonical part and its OpenCode addendum."""

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.rstrip("\r\n") == OPENCODE_SECTION_HEADING:
            base = "".join(lines[:index]).rstrip("\n") + "\n"
            return base, "".join(lines[index:]).rstrip("\n") + "\n"
    return text, None


def render_opencode_skill(canonical: str, addendum: str | None) -> str:
    """Canonical skill followed by the OpenCode addendum, deterministically."""

    base, _ = split_opencode_section(canonical)
    if addendum is None:
        return base
    return f"{base.rstrip(chr(10))}\n\n{addendum.rstrip(chr(10))}\n"


def _plan_opencode_target(
    home: Path,
    stable_key: str,
    rendered: str,
    managed_hash: str | None,
) -> SkillTargetPlan:
    path = home.joinpath(*_OPENCODE_SKILLS_DIR, stable_key, "SKILL.md")
    if not path.exists():
        return SkillTargetPlan("opencode", path, "missing", None, None, rendered)
    if not path.is_file():
        raise SkillSyncError(f"skill target is not a regular file: {path}")
    try:
        current = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillSyncError(f"skill target is not valid UTF-8: {path}") from exc
    current_base, addendum = split_opencode_section(current)
    desired = render_opencode_skill(rendered, addendum)
    state = classify_state(current_base, rendered, managed_hash)
    if state == "current" and current != desired:
        state = "outdated"
    return SkillTargetPlan("opencode", path, state, current, _sha256(current), desired)


def _plan_target(
    home: Path,
    stable_key: str,
    harness: Literal["agents", "claude"],
    rendered: str,
    managed_hash: str | None,
) -> SkillTargetPlan:
    path = home / f".{harness}" / "skills" / stable_key / "SKILL.md"
    if not path.exists():
        return SkillTargetPlan(harness, path, "missing", None, None)
    if not path.is_file():
        raise SkillSyncError(f"skill target is not a regular file: {path}")
    try:
        current = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillSyncError(f"skill target is not valid UTF-8: {path}") from exc
    current_hash = _sha256(current)
    state = classify_state(current, rendered, managed_hash)
    return SkillTargetPlan(harness, path, state, current, current_hash)


def _plan_retired_targets(
    home: Path,
    stable_key: str,
    rendered: str | None,
    managed_hash: str | None,
    opencode_hash: str | None,
    *,
    include_opencode: bool,
) -> list[SkillTargetPlan]:
    """Managed, unmodified copies of a deprecated skill; anything else is left alone."""

    paths: list[tuple[Literal["agents", "claude", "opencode"], Path, str | None]] = [
        ("agents", home / ".agents" / "skills" / stable_key / "SKILL.md", managed_hash),
        ("claude", home / ".claude" / "skills" / stable_key / "SKILL.md", managed_hash),
    ]
    if include_opencode:
        paths.append(
            (
                "opencode",
                home.joinpath(*_OPENCODE_SKILLS_DIR, stable_key, "SKILL.md"),
                opencode_hash,
            )
        )
    retired: list[SkillTargetPlan] = []
    for harness, path, digest in paths:
        if not path.is_file():
            continue
        try:
            current = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if harness == "opencode" and split_opencode_section(current)[1] is not None:
            continue
        current_hash = _sha256(current)
        if current == rendered or (digest is not None and current_hash == digest):
            retired.append(SkillTargetPlan(harness, path, "outdated", current, current_hash))
    return retired


def _load_managed_hashes(manifest_path: Path, target: str | None = None) -> dict[str, str]:
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        return {}
    rows = payload.get("skills")
    if not isinstance(rows, list):
        return {}
    hashes: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        stable_key = row.get("stable_key")
        digest = row.get("sha256")
        per_target = row.get("target_sha256")
        if target is not None and isinstance(per_target, dict):
            digest = per_target.get(target, digest)
        if isinstance(stable_key, str) and isinstance(digest, str):
            hashes[stable_key] = digest
    return hashes


def _verify_plan_is_fresh(plan: SkillSyncPlan) -> None:
    if plan.manifest_path.exists() and not plan.manifest_path.is_file():
        raise SkillSyncConflictError("skill manifest changed since planning")
    manifest = (
        plan.manifest_path.read_text(encoding="utf-8") if plan.manifest_path.is_file() else None
    )
    if manifest != plan.manifest_before:
        raise SkillSyncConflictError("skill manifest changed since planning")
    targets = [target for entry in plan.entries for target in entry.all_files]
    for target in [*targets, *plan.retired]:
        if target.path.exists():
            if not target.path.is_file():
                raise SkillSyncConflictError(f"skill target changed since planning: {target.path}")
            current_hash = _sha256(target.path.read_text(encoding="utf-8"))
        else:
            current_hash = None
        if current_hash != target.current_sha256:
            raise SkillSyncConflictError(f"skill target changed since planning: {target.path}")


def _backup_path(
    backup_root: Path,
    stable_key: str,
    harness: Literal["agents", "claude", "opencode"],
    rel: str | None = None,
) -> Path:
    key_root = backup_root / stable_key
    name = rel or "SKILL.md"
    if harness == "agents":
        return key_root / name
    return key_root / harness / name


def _validate_files(files: Sequence[tuple[str, str]]) -> None:
    for path, _ in files:
        error = skill_file_path_error(path)
        if error:
            raise SkillSyncError(f"unsafe auxiliary skill file {path!r}: {error}")


def _skill_dirs(
    home: Path, stable_key: str, *, include_opencode: bool
) -> tuple[tuple[Literal["agents", "claude", "opencode"], Path], ...]:
    dirs: list[tuple[Literal["agents", "claude", "opencode"], Path]] = [
        ("agents", home / ".agents" / "skills" / stable_key),
        ("claude", home / ".claude" / "skills" / stable_key),
    ]
    if include_opencode:
        dirs.append(("opencode", home.joinpath(*_OPENCODE_SKILLS_DIR, stable_key)))
    return tuple(dirs)


def _assert_no_symlink(home: Path, path: Path) -> None:
    """Refuse to read or write through a symlink anywhere below the managed home."""

    current = path
    while current != home and current != current.parent:
        if current.is_symlink():
            raise SkillSyncError(f"refusing to follow a symlink: {current}")
        current = current.parent


def _plan_aux_targets(
    home: Path,
    stable_key: str,
    files: Sequence[tuple[str, str]],
    managed: dict[str, str],
    *,
    include_opencode: bool,
) -> tuple[SkillTargetPlan, ...]:
    targets: list[SkillTargetPlan] = []
    for harness, base in _skill_dirs(home, stable_key, include_opencode=include_opencode):
        for rel, text in files:
            path = base.joinpath(*rel.split("/"))
            _assert_no_symlink(home, path)
            if not path.exists():
                targets.append(SkillTargetPlan(harness, path, "missing", None, None, text, rel))
                continue
            if not path.is_file():
                raise SkillSyncError(f"skill file target is not a regular file: {path}")
            try:
                current = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise SkillSyncError(f"skill file target is not valid UTF-8: {path}") from exc
            state = classify_state(current, text, managed.get(rel))
            targets.append(
                SkillTargetPlan(harness, path, state, current, _sha256(current), text, rel)
            )
    return tuple(targets)


def _plan_removed_files(
    home: Path,
    stable_key: str,
    managed: dict[str, str],
    keep: frozenset[str],
    *,
    include_opencode: bool,
) -> list[SkillTargetPlan]:
    """Managed, unmodified auxiliary files no longer wanted; modified ones are left alone."""

    removed: list[SkillTargetPlan] = []
    for harness, base in _skill_dirs(home, stable_key, include_opencode=include_opencode):
        for rel, digest in sorted(managed.items()):
            if rel in keep or skill_file_path_error(rel):
                continue
            path = base.joinpath(*rel.split("/"))
            if path.is_symlink() or not path.is_file():
                continue
            try:
                current = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if _sha256(current) == digest:
                removed.append(
                    SkillTargetPlan(harness, path, "outdated", current, digest, None, rel)
                )
    return removed


def _prune_empty_dirs(directory: Path, home: Path) -> None:
    """Remove now-empty directories up to, never including, a skills root."""

    roots = {
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home.joinpath(*_OPENCODE_SKILLS_DIR),
    }
    while directory != home and directory not in roots and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent


def _load_managed_files(manifest_path: Path) -> dict[str, dict[str, str]]:
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    rows = payload.get("skills") if isinstance(payload, dict) else None
    result: dict[str, dict[str, str]] = {}
    for row in rows if isinstance(rows, list) else []:
        files = row.get("files") if isinstance(row, dict) else None
        if isinstance(files, dict) and isinstance(row.get("stable_key"), str):
            result[row["stable_key"]] = {
                k: v for k, v in files.items() if isinstance(k, str) and isinstance(v, str)
            }
    return result


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


def _sha256(text: str) -> str:
    from studio_client.drift import hash_text

    return hash_text(text)
