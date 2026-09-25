"""Project effective Studio Library skills into global harness directories."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from studio_client.context.library import LibraryContextItem, LibraryContextProvider

SyncState = Literal["current", "missing", "outdated", "locally_modified"]

_STABLE_KEY_RE = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,199}\Z")
_MANIFEST_SCHEMA_VERSION = 1
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class SkillSyncError(RuntimeError):
    """Base error for invalid or unsafe skill synchronization."""


class SkillSyncConflictError(SkillSyncError):
    """Raised when a synchronization would overwrite local content."""


@dataclass(frozen=True)
class SkillTargetPlan:
    """Desired state of one harness copy of a skill."""

    harness: Literal["agents", "claude"]
    path: Path
    state: SyncState
    current_text: str | None
    current_sha256: str | None


@dataclass(frozen=True)
class SkillPlanEntry:
    """Rendered skill and the two harness destinations that consume it."""

    projection: LibraryContextItem
    rendered: str
    sha256: str
    targets: tuple[SkillTargetPlan, SkillTargetPlan]


@dataclass(frozen=True)
class SkillSyncPlan:
    """A deterministic, side-effect-free synchronization plan."""

    home: Path
    entries: tuple[SkillPlanEntry, ...]
    manifest_path: Path
    manifest_text: str

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
            for target in entry.targets
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
            target for entry in self.entries for target in entry.targets if target.state == state
        )


@dataclass(frozen=True)
class SkillSyncResult:
    """Files written and backups created by an applied plan."""

    written: tuple[Path, ...]
    backups: tuple[Path, ...]
    manifest_path: Path


async def fetch_skill_projections(
    api: Any,
    project_id: UUID | None,
    limit: int = 100,
) -> tuple[LibraryContextItem, ...]:
    """Fetch effective skills and keep only globally safe Studio-scope rows."""

    result = await LibraryContextProvider(api).fetch(
        project_id,
        limit=limit,
        kinds=("skill",),
    )
    return tuple(
        sorted(
            (item for item in result.items if item.scope == "studio"),
            key=lambda item: item.stable_key,
        )
    )


def render_skill(projection: LibraryContextItem) -> str:
    """Render a Library skill as a harness-compatible ``SKILL.md``."""

    _validate_projection(projection)
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
) -> SkillSyncPlan:
    """Inspect global skill targets without changing the filesystem."""

    root = Path(home).expanduser().resolve()
    manifest_path = root / ".studio-os" / "library-skills-manifest.json"
    managed_hashes = _load_managed_hashes(manifest_path)
    entries: list[SkillPlanEntry] = []
    seen: set[str] = set()
    for projection in sorted(projections, key=lambda item: item.stable_key):
        _validate_projection(projection)
        if projection.stable_key in seen:
            raise SkillSyncError(f"duplicate skill stable_key: {projection.stable_key!r}")
        seen.add(projection.stable_key)
        rendered = render_skill(projection)
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
        entries.append(
            SkillPlanEntry(
                projection=projection,
                rendered=rendered,
                sha256=desired_hash,
                targets=targets,
            )
        )

    manifest = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "skills": [
            {
                "scope": entry.projection.scope,
                "sha256": entry.sha256,
                "stable_key": entry.projection.stable_key,
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
    )


def diff_skill_plan(plan: SkillSyncPlan) -> str:
    """Return deterministic unified diffs for missing and drifted targets."""

    chunks: list[str] = []
    for entry in plan.entries:
        desired_lines = entry.rendered.splitlines(keepends=True)
        for target in entry.targets:
            if target.state == "current":
                continue
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
) -> SkillSyncResult:
    """Apply a plan atomically per file, backing up authorized overwrites."""

    conflicts = [target for target in plan.locally_modified]
    if conflicts and not overwrite:
        paths = ", ".join(str(target.path) for target in conflicts)
        raise SkillSyncConflictError(
            f"refusing to overwrite locally modified skill files without overwrite=True: {paths}"
        )
    _verify_plan_is_fresh(plan)

    backup_root: Path | None = None
    backups: list[Path] = []
    if conflicts:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_root = plan.home / ".studio-os" / "backups" / "skills" / timestamp
        for entry in plan.entries:
            for target in entry.targets:
                if target.state != "locally_modified" or target.current_text is None:
                    continue
                backup_path = _backup_path(
                    backup_root,
                    entry.projection.stable_key,
                    target.harness,
                )
                _atomic_write(backup_path, target.current_text)
                backups.append(backup_path)

    written: list[Path] = []
    for entry in plan.entries:
        for target in entry.targets:
            if target.state == "current":
                continue
            _atomic_write(target.path, entry.rendered)
            written.append(target.path)
    _atomic_write(plan.manifest_path, plan.manifest_text)
    return SkillSyncResult(
        written=tuple(written),
        backups=tuple(backups),
        manifest_path=plan.manifest_path,
    )


def _validate_projection(projection: LibraryContextItem) -> None:
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
    if projection.scope != "studio":
        raise SkillSyncError(
            f"refusing to project non-studio skill {key!r} with scope {projection.scope!r}"
        )
    if projection.version <= 0:
        raise SkillSyncError(f"invalid skill version for {key!r}: {projection.version}")


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
    if current == rendered:
        state: SyncState = "current"
    elif managed_hash is not None and current_hash == managed_hash:
        state = "outdated"
    else:
        state = "locally_modified"
    return SkillTargetPlan(harness, path, state, current, current_hash)


def _load_managed_hashes(manifest_path: Path) -> dict[str, str]:
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
        if isinstance(stable_key, str) and isinstance(digest, str):
            hashes[stable_key] = digest
    return hashes


def _verify_plan_is_fresh(plan: SkillSyncPlan) -> None:
    for entry in plan.entries:
        for target in entry.targets:
            if target.path.exists():
                if not target.path.is_file():
                    raise SkillSyncConflictError(
                        f"skill target changed since planning: {target.path}"
                    )
                current_hash = _sha256(target.path.read_text(encoding="utf-8"))
            else:
                current_hash = None
            if current_hash != target.current_sha256:
                raise SkillSyncConflictError(f"skill target changed since planning: {target.path}")


def _backup_path(
    backup_root: Path,
    stable_key: str,
    harness: Literal["agents", "claude"],
) -> Path:
    key_root = backup_root / stable_key
    if harness == "agents":
        return key_root / "SKILL.md"
    return key_root / "claude" / "SKILL.md"


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
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
