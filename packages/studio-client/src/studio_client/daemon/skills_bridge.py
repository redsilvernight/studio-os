"""Bridge commands for skills synchronization.

Provides ``skills.check`` (read-only), ``skills.preview`` (diff), ``skills.apply``
(apply with confirmation), and ``skills.status`` (persisted sync status).
Auto-sync at daemon startup is orchestrated from ``daemon.runtime``.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.skills import (
    SkillCheckEntry,
    SkillHarnessTarget,
    SkillLibraryKind,
    SkillPreviewEntry,
    SkillsApplyRequest,
    SkillsApplyResult,
    SkillsCheckResult,
    SkillsConfigureRequest,
    SkillsPreviewResult,
    SkillsSyncStatus,
    SkillSyncState,
    SkillSyncStatusState,
    SkillTargetState,
)

from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.context.errors import ContextError
from studio_client.context.library import LibraryContextItem, LibraryContextProvider
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.drift import (
    SyncState,
    classify_state,
    dump_manifest_v2,
    hash_text,
    load_managed_hashes,
)
from studio_client.errors import AuthenticationError, StudioApiError
from studio_client.projection_backups import commit_projection_backup, prepare_projection_backup
from studio_client.skill_sync import (
    _STABLE_KEY_RE,
    _WINDOWS_RESERVED_NAMES,
    SkillPlanEntry,
    SkillSyncConflictError,
    SkillSyncError,
    SkillSyncPlan,
    SkillSyncResult,
    SkillTargetPlan,
    _atomic_write,
    apply_skill_sync,
    diff_skill_plan,
    fetch_skill_projections,
    plan_skill_sync,
)
from studio_client.tokens import TokenStore, origin_of

_LOGGER = logging.getLogger("studio_client.daemon.skills_bridge")

_SKILL_LIMIT = 100

# The contract stays vendor-neutral: the wire names the global skill
# directories by role, not by product.
_HARNESS = {
    "agents": SkillHarnessTarget.AGENTS,
    "claude": SkillHarnessTarget.ASSISTANT,
}

_STATUS_FILE_NAME = "skills-sync-status.json"
_SETTINGS_FILE_NAME = "skills-sync-settings.json"
_DEFINITIONS_MANIFEST_NAME = "library-definitions-manifest.json"

_DEFINITION_KINDS = frozenset({"rule", "agent_definition"})
_GLOBAL_SCOPES = frozenset({"studio", "user"})


def _status_path(data_root: Path) -> Path:
    return data_root / _STATUS_FILE_NAME


@dataclass(frozen=True)
class DefinitionTargetPlan:
    harness: Literal["agents", "claude"]
    path: Path
    state: SyncState
    current_text: str | None
    current_sha256: str | None
    desired_text: str


@dataclass(frozen=True)
class DefinitionPlanEntry:
    projection: LibraryContextItem
    rendered: str
    sha256: str
    targets: tuple[DefinitionTargetPlan, DefinitionTargetPlan]

    @property
    def all_targets(self) -> tuple[DefinitionTargetPlan, ...]:
        return self.targets


@dataclass(frozen=True)
class DefinitionSyncPlan:
    home: Path
    entries: tuple[DefinitionPlanEntry, ...]
    manifest_path: Path
    manifest_text: str
    retired: tuple[DefinitionTargetPlan, ...] = ()
    manifest_before: str | None = None

    @property
    def current(self) -> tuple[DefinitionTargetPlan, ...]:
        return self._targets_with_state("current")

    @property
    def missing(self) -> tuple[DefinitionTargetPlan, ...]:
        return self._targets_with_state("missing")

    @property
    def outdated(self) -> tuple[DefinitionTargetPlan, ...]:
        return self._targets_with_state("outdated")

    @property
    def locally_modified(self) -> tuple[DefinitionTargetPlan, ...]:
        return self._targets_with_state("locally_modified")

    def _targets_with_state(self, state: SyncState) -> tuple[DefinitionTargetPlan, ...]:
        return tuple(
            target
            for entry in self.entries
            for target in entry.all_targets
            if target.state == state
        )


def _error(
    code: LocalErrorCode,
    message: str,
    component: ComponentId,
    *,
    retryable: bool,
) -> LocalFeatureError:
    return LocalFeatureError(
        LocalError(code=code, message=message, component=component, retryable=retryable)
    )


def _load_status(data_root: Path) -> SkillsSyncStatus | None:
    path = _status_path(data_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SkillsSyncStatus.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _save_status(data_root: Path, status: SkillsSyncStatus) -> None:
    path = _status_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(status.model_dump_json(indent=2), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)


def _manifest_kind(library_kind: str) -> str:
    return "agent" if library_kind == "agent_definition" else library_kind


def _definition_paths(
    home: Path, library_kind: str, stable_key: str
) -> tuple[tuple[Literal["agents", "claude"], Path], ...]:
    if library_kind == "rule":
        return (
            ("agents", home / ".agents" / "rules" / f"{stable_key}.md"),
            ("claude", home / ".claude" / "rules" / f"{stable_key}.md"),
        )
    return (
        ("agents", home / ".agents" / "definitions" / f"{stable_key}.md"),
        ("claude", home / ".claude" / "agents" / f"{stable_key}.md"),
    )


def render_definition(projection: LibraryContextItem) -> str:
    _validate_definition_projection(projection)
    description = " ".join((projection.description or "").split())
    if not description:
        description = " ".join(projection.title.split())
    body = projection.text.replace("\r\n", "\n").replace("\r", "\n").strip()
    provenance = (
        "<!-- studio-os-library: "
        f"kind={projection.library_kind}; stable_key={projection.stable_key}; "
        f"version={projection.version}; version_origin={projection.version_origin}; "
        f"scope={projection.scope} -->"
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


def _validate_definition_projection(projection: LibraryContextItem) -> None:
    key = projection.stable_key
    windows_stem = key.split(".", 1)[0].upper()
    if (
        not _STABLE_KEY_RE.fullmatch(key)
        or key in {".", ".."}
        or ".." in key
        or key.endswith(".")
        or windows_stem in _WINDOWS_RESERVED_NAMES
    ):
        raise SkillSyncError(f"unsafe definition stable_key: {key!r}")
    if projection.library_kind not in _DEFINITION_KINDS:
        raise SkillSyncError(
            f"expected a rule or agent_definition projection, got {projection.library_kind!r}"
        )
    if projection.scope not in _GLOBAL_SCOPES:
        raise SkillSyncError(
            f"refusing to project definition {key!r} with scope {projection.scope!r}"
        )
    if projection.version <= 0:
        raise SkillSyncError(f"invalid definition version for {key!r}: {projection.version}")


async def fetch_library_projections(
    api: Any,
    project_id: Any,
    limit: int = 100,
) -> tuple[LibraryContextItem, ...]:
    provider = LibraryContextProvider(api)
    textual = await provider.fetch(project_id, limit=limit, kinds=("rule", "skill"))
    items = [item for item in textual.items if item.scope in _GLOBAL_SCOPES]

    for row in await provider.fetch_effective_versions(
        project_id, kind="agent_definition", limit=limit
    ):
        status = str(getattr(row.resource, "status", "active"))
        if status not in {"active", "deprecated"}:
            continue
        if str(row.resource.scope) not in _GLOBAL_SCOPES:
            continue
        content = dict(row.version_row.content)
        parts = [
            str(content[field]).strip()
            for field in ("summary", "intended_use")
            if isinstance(content.get(field), str) and str(content[field]).strip()
        ]
        items.append(
            LibraryContextItem(
                library_kind="agent_definition",
                stable_key=row.resource.stable_key,
                version=row.version,
                version_origin=row.version_origin,
                scope=str(row.resource.scope),
                title=row.version_row.title,
                text="\n\n".join(parts),
                content_schema=str(
                    content.get("content_schema", "studio.library.agent_definition/v1")
                ),
                deprecated=status == "deprecated",
            )
        )

    return tuple(sorted(items, key=lambda item: (item.library_kind, item.stable_key)))


def plan_definition_sync(
    home: Path | str,
    projections: tuple[LibraryContextItem, ...] | list[LibraryContextItem],
) -> DefinitionSyncPlan:
    root = Path(home).expanduser().resolve()
    manifest_path = root / ".studio-os" / _DEFINITIONS_MANIFEST_NAME
    manifest_before = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else None
    managed_hashes = load_managed_hashes(manifest_path)
    entries: list[DefinitionPlanEntry] = []
    retired: list[DefinitionTargetPlan] = []
    seen: set[tuple[str, str]] = set()

    for projection in sorted(
        projections, key=lambda item: (_manifest_kind(item.library_kind), item.stable_key)
    ):
        _validate_definition_projection(projection)
        manifest_kind = _manifest_kind(projection.library_kind)
        identity = (manifest_kind, projection.stable_key)
        if identity in seen:
            raise SkillSyncError(
                f"duplicate {projection.library_kind} stable_key: {projection.stable_key!r}"
            )
        seen.add(identity)
        rendered = render_definition(projection)
        desired_hash = hash_text(rendered)
        managed_hash = managed_hashes.get(identity)

        if projection.deprecated:
            retired.extend(
                _plan_retired_definition(
                    root, projection.library_kind, projection.stable_key, rendered, managed_hash
                )
            )
            continue

        agents_target = _plan_definition_target(
            root, projection.library_kind, projection.stable_key, "agents", rendered, managed_hash
        )
        claude_target = _plan_definition_target(
            root, projection.library_kind, projection.stable_key, "claude", rendered, managed_hash
        )
        entries.append(
            DefinitionPlanEntry(
                projection=projection,
                rendered=rendered,
                sha256=desired_hash,
                targets=(agents_target, claude_target),
            )
        )

    manifest_text = dump_manifest_v2(
        [
            {
                "kind": _manifest_kind(entry.projection.library_kind),
                "scope": entry.projection.scope,
                "sha256": entry.sha256,
                "stable_key": entry.projection.stable_key,
                "version": entry.projection.version,
                "version_origin": entry.projection.version_origin,
            }
            for entry in entries
        ]
    )
    return DefinitionSyncPlan(
        home=root,
        entries=tuple(entries),
        manifest_path=manifest_path,
        manifest_text=manifest_text,
        retired=tuple(retired),
        manifest_before=manifest_before,
    )


def _plan_definition_target(
    home: Path,
    library_kind: str,
    stable_key: str,
    harness: Literal["agents", "claude"],
    rendered: str,
    managed_hash: str | None,
) -> DefinitionTargetPlan:
    path = dict(_definition_paths(home, library_kind, stable_key))[harness]
    if not path.exists():
        return DefinitionTargetPlan(harness, path, "missing", None, None, rendered)
    if not path.is_file():
        raise SkillSyncError(f"definition target is not a regular file: {path}")
    try:
        current = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillSyncError(f"definition target is not valid UTF-8: {path}") from exc
    state = classify_state(current, rendered, managed_hash)
    return DefinitionTargetPlan(harness, path, state, current, hash_text(current), rendered)


def _plan_retired_definition(
    home: Path,
    library_kind: str,
    stable_key: str,
    rendered: str,
    managed_hash: str | None,
) -> list[DefinitionTargetPlan]:
    retired: list[DefinitionTargetPlan] = []
    for harness, path in _definition_paths(home, library_kind, stable_key):
        if not path.is_file():
            continue
        try:
            current = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if current == rendered or (managed_hash is not None and hash_text(current) == managed_hash):
            retired.append(
                DefinitionTargetPlan(
                    harness, path, "outdated", current, hash_text(current), rendered
                )
            )
    return retired


def _verify_definition_plan_is_fresh(plan: DefinitionSyncPlan) -> None:
    if plan.manifest_path.exists() and not plan.manifest_path.is_file():
        raise SkillSyncConflictError("definition manifest changed since planning")
    manifest = (
        plan.manifest_path.read_text(encoding="utf-8") if plan.manifest_path.is_file() else None
    )
    if manifest != plan.manifest_before:
        raise SkillSyncConflictError("definition manifest changed since planning")
    for target in [*(t for e in plan.entries for t in e.all_targets), *plan.retired]:
        if target.path.exists():
            if not target.path.is_file():
                raise SkillSyncConflictError(
                    f"definition target changed since planning: {target.path}"
                )
            try:
                current_hash = hash_text(target.path.read_text(encoding="utf-8"))
            except UnicodeDecodeError as exc:
                raise SkillSyncConflictError(
                    f"definition target changed since planning: {target.path}"
                ) from exc
        else:
            current_hash = None
        if current_hash != target.current_sha256:
            raise SkillSyncConflictError(f"definition target changed since planning: {target.path}")


def _select_definitions(
    plan: DefinitionSyncPlan, selected: set[tuple[str, str]]
) -> DefinitionSyncPlan:
    known = {
        (_manifest_kind(e.projection.library_kind), e.projection.stable_key) for e in plan.entries
    }
    if selected - known:
        raise SkillSyncError("unknown definition selection")
    manifest = json.loads(plan.manifest_text)
    previous_text = (
        plan.manifest_path.read_text(encoding="utf-8") if plan.manifest_path.is_file() else None
    )
    previous = json.loads(previous_text) if previous_text is not None else {}
    if not isinstance(previous, dict) or not isinstance(previous.get("items", []), list):
        raise SkillSyncError("invalid existing definition manifest")

    def identity(row: Any) -> tuple[Any, Any]:
        return (row.get("kind"), row.get("stable_key")) if isinstance(row, dict) else (None, None)

    items = [
        row
        for row in previous.get("items", [])
        if isinstance(row, dict) and identity(row) not in selected
    ] + [row for row in manifest["items"] if identity(row) in selected]
    return replace(
        plan,
        entries=tuple(
            entry
            for entry in plan.entries
            if (_manifest_kind(entry.projection.library_kind), entry.projection.stable_key)
            in selected
        ),
        retired=(),
        manifest_text=dump_manifest_v2(items),
        manifest_before=previous_text,
    )


def apply_definition_sync(
    plan: DefinitionSyncPlan,
    *,
    overwrite: bool = False,
    selected: set[tuple[str, str]] | None = None,
) -> SkillSyncResult:
    if selected is not None:
        if not selected:
            return SkillSyncResult(
                written=(), backups=(), manifest_path=plan.manifest_path, removed=()
            )
        plan = _select_definitions(plan, selected)
    conflicts = list(plan.locally_modified)
    if conflicts and not overwrite:
        paths = ", ".join(str(target.path) for target in conflicts)
        raise SkillSyncConflictError(
            "refusing to overwrite locally modified definition files "
            f"without overwrite=True: {paths}"
        )
    _verify_definition_plan_is_fresh(plan)

    desired: dict[Path, str | None] = {
        target.path: target.desired_text
        for entry in plan.entries
        for target in entry.all_targets
        if target.state != "current"
    }
    desired.update({target.path: None for target in plan.retired})
    desired[plan.manifest_path] = plan.manifest_text
    journal = prepare_projection_backup(plan.home, desired)
    _verify_definition_plan_is_fresh(plan)

    backup_root: Path | None = None
    backups: list[Path] = []
    if conflicts:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_root = plan.home / ".studio-os" / "backups" / "definitions" / timestamp
        for entry in plan.entries:
            for target in entry.all_targets:
                if target.state != "locally_modified" or target.current_text is None:
                    continue
                backup_path = (
                    backup_root
                    / _manifest_kind(entry.projection.library_kind)
                    / entry.projection.stable_key
                    / target.harness
                    / "definition.md"
                )
                _atomic_write(backup_path, target.current_text)
                backups.append(backup_path)

    written: list[Path] = []
    for entry in plan.entries:
        for target in entry.all_targets:
            if target.state == "current":
                continue
            _atomic_write(target.path, target.desired_text)
            written.append(target.path)

    removed: list[Path] = []
    for target in plan.retired:
        target.path.unlink()
        removed.append(target.path)
        try:
            target.path.parent.rmdir()
        except OSError:
            pass

    _atomic_write(plan.manifest_path, plan.manifest_text)
    commit_projection_backup(journal)
    return SkillSyncResult(
        written=tuple(written),
        backups=tuple(backups),
        manifest_path=plan.manifest_path,
        removed=tuple(removed),
    )


def plan_library_sync(
    home: Path,
    projections: tuple[LibraryContextItem, ...] | list[LibraryContextItem],
) -> tuple[SkillSyncPlan, DefinitionSyncPlan]:
    skills = [
        item
        for item in projections
        if item.library_kind == "skill" and item.scope in _GLOBAL_SCOPES
    ]
    definitions = [
        item
        for item in projections
        if item.library_kind in _DEFINITION_KINDS and item.scope in _GLOBAL_SCOPES
    ]
    return plan_skill_sync(home, skills), plan_definition_sync(home, definitions)


def _run_fetch(
    config: ClientConfig,
    token_store: TokenStore,
    fetcher: Callable[[ClientConfig, TokenStore], Any],
) -> tuple[LibraryContextItem, ...]:
    if not token_store.get_token(origin_of(config.api_base_url)):
        raise _error(
            LocalErrorCode.SECRET_ABSENT,
            "No machine credential is stored.",
            ComponentId.SECRET_STORE,
            retryable=False,
        )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return tuple(pool.submit(asyncio.run, fetcher(config, token_store)).result())
    except AuthenticationError as exc:
        raise _error(
            LocalErrorCode.SECRET_REVOKED,
            "The machine credential was rejected.",
            ComponentId.SECRET_STORE,
            retryable=False,
        ) from exc
    except StudioApiError as exc:
        _LOGGER.warning("skills.sync: library unreachable (%s)", type(exc).__name__)
        raise _error(
            LocalErrorCode.INTERNAL_ERROR,
            "The Studio OS Library could not be reached.",
            ComponentId.DAEMON,
            retryable=True,
        ) from exc
    except (SkillSyncError, ContextError) as exc:
        _LOGGER.warning("skills.sync: invalid library definition (%s)", type(exc).__name__)
        raise _error(
            LocalErrorCode.INTERNAL_ERROR,
            "A Library definition could not be checked.",
            ComponentId.DAEMON,
            retryable=False,
        ) from exc


def _fetch_projections(
    config: ClientConfig, token_store: TokenStore
) -> tuple[LibraryContextItem, ...]:
    return _run_fetch(config, token_store, _fetch)


def _fetch_skill_projections(
    config: ClientConfig, token_store: TokenStore
) -> tuple[LibraryContextItem, ...]:
    return _run_fetch(config, token_store, _fetch_skills_only)


def _fetch_and_plan(
    config: ClientConfig,
    token_store: TokenStore,
    home: Path,
) -> SkillSyncPlan:
    projections = _fetch_skill_projections(config, token_store)
    return plan_skill_sync(home, projections)


def _fetch_and_plan_library(
    config: ClientConfig,
    token_store: TokenStore,
    home: Path,
) -> tuple[SkillSyncPlan, DefinitionSyncPlan]:
    return plan_library_sync(home, _fetch_projections(config, token_store))


async def _fetch(config: ClientConfig, token_store: TokenStore) -> Any:
    async with StudioApiClient(config, token_store) as client:
        return await fetch_library_projections(client, None, limit=_SKILL_LIMIT)


async def _fetch_skills_only(config: ClientConfig, token_store: TokenStore) -> Any:
    async with StudioApiClient(config, token_store) as client:
        return await fetch_skill_projections(client, None, limit=_SKILL_LIMIT)


def summarize(plan: SkillSyncPlan, *, checked_at: datetime | None = None) -> SkillsCheckResult:
    entries = [
        SkillCheckEntry(
            stable_key=entry.projection.stable_key,
            version=entry.projection.version,
            targets=[
                SkillTargetState(
                    harness=_HARNESS[target.harness], state=SkillSyncState(target.state)
                )
                for target in entry.all_targets
            ],
        )
        for entry in plan.entries
    ]
    drifted = len(plan.drifted)
    return SkillsCheckResult(
        skills=entries,
        current=len(plan.current),
        missing=len(plan.missing),
        outdated=len(plan.outdated),
        locally_modified=len(plan.locally_modified),
        in_sync=not plan.missing and not plan.retired and drifted == 0,
        checked_at=checked_at or datetime.now(UTC),
    )


def check_skills(
    config: ClientConfig,
    token_store: TokenStore,
    *,
    home: Path | None = None,
) -> SkillsCheckResult:
    """Compare the effective Library skills with the local harness copies."""
    plan = _fetch_and_plan(config, token_store, home if home is not None else Path.home())
    return summarize(plan)


def _preview_hash(entry: SkillPlanEntry) -> str:
    payload = {
        "stable_key": entry.projection.stable_key,
        "version": entry.projection.version,
        "desired_sha256": entry.sha256,
        "targets": [(target.harness, target.current_sha256) for target in entry.all_targets],
    }
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _definition_kind(entry: DefinitionPlanEntry) -> SkillLibraryKind:
    return SkillLibraryKind(_manifest_kind(entry.projection.library_kind))


def _definition_preview_hash(entry: DefinitionPlanEntry) -> str:
    payload = {
        "kind": _manifest_kind(entry.projection.library_kind),
        "stable_key": entry.projection.stable_key,
        "version": entry.projection.version,
        "desired_sha256": entry.sha256,
        "targets": [(target.harness, target.current_sha256) for target in entry.all_targets],
    }
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _diff_definition_entry(home: Path, entry: DefinitionPlanEntry) -> str:
    chunks: list[str] = []
    for target in entry.all_targets:
        if target.state == "current":
            continue
        relative = target.path.relative_to(home).as_posix()
        current_lines = (
            [] if target.current_text is None else target.current_text.splitlines(keepends=True)
        )
        chunks.extend(
            difflib.unified_diff(
                current_lines,
                target.desired_text.splitlines(keepends=True),
                fromfile="/dev/null" if target.state == "missing" else relative,
                tofile=relative,
            )
        )
    return "".join(chunks)


def _target_label(
    plan: SkillSyncPlan | DefinitionSyncPlan,
    target: SkillTargetPlan | DefinitionTargetPlan,
) -> str:
    return target.path.relative_to(plan.home).as_posix()


def _sync_paths(
    plans: tuple[SkillSyncPlan | DefinitionSyncPlan, ...],
) -> dict[Path, bytes | None]:
    snapshot: dict[Path, bytes | None] = {}
    for plan in plans:
        snapshot[plan.manifest_path] = (
            plan.manifest_path.read_bytes() if plan.manifest_path.is_file() else None
        )
        targets = [target for entry in plan.entries for target in entry.all_targets]
        targets.extend(plan.retired)
        for target in targets:
            snapshot[target.path] = target.path.read_bytes() if target.path.is_file() else None
    return snapshot


def _restore_paths(snapshot: dict[Path, bytes | None]) -> None:
    for path, data in snapshot.items():
        if data is None:
            if path.is_file():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.rollback")
        temporary.write_bytes(data)
        os.replace(temporary, path)


def _restore_after_failure(snapshot: dict[Path, bytes | None]) -> None:
    try:
        _restore_paths(snapshot)
    except OSError:
        _LOGGER.exception("skills.apply: rollback failed")


def preview_skills(
    config: ClientConfig,
    token_store: TokenStore,
    *,
    home: Path | None = None,
) -> SkillsPreviewResult:
    """Return a preview (unified diff) of the skill, rule and agent synchronization plan."""
    plan, definitions = _fetch_and_plan_library(
        config, token_store, home if home is not None else Path.home()
    )
    entries = [
        SkillPreviewEntry(
            stable_key=entry.projection.stable_key,
            version=entry.projection.version,
            targets=[
                SkillTargetState(
                    harness=_HARNESS[target.harness], state=SkillSyncState(target.state)
                )
                for target in entry.targets
            ],
            diff=diff_skill_plan(replace(plan, entries=(entry,), retired=())),
            preview_hash=_preview_hash(entry),
        )
        for entry in plan.entries
    ] + [
        SkillPreviewEntry(
            kind=_definition_kind(entry),
            stable_key=entry.projection.stable_key,
            version=entry.projection.version,
            targets=[
                SkillTargetState(
                    harness=_HARNESS[target.harness], state=SkillSyncState(target.state)
                )
                for target in entry.all_targets
            ],
            diff=_diff_definition_entry(definitions.home, entry),
            preview_hash=_definition_preview_hash(entry),
        )
        for entry in definitions.entries
    ]
    diff_text = diff_skill_plan(plan)
    return SkillsPreviewResult(
        skills=entries,
        current=len(plan.current),
        missing=len(plan.missing),
        outdated=len(plan.outdated),
        locally_modified=len(plan.locally_modified),
        diff=diff_text,
        checked_at=datetime.now(UTC),
    )


def apply_skills(
    config: ClientConfig,
    token_store: TokenStore,
    request: SkillsApplyRequest,
    *,
    home: Path | None = None,
    data_root: Path | None = None,
) -> SkillsApplyResult:
    """Apply the skill synchronization plan. Requires explicit confirmation."""
    if not request.confirm:
        raise _error(
            LocalErrorCode.INVALID_REQUEST,
            "Explicit confirmation is required to apply skill changes.",
            ComponentId.DAEMON,
            retryable=False,
        )
    root = home if home is not None else Path.home()
    definitions: DefinitionSyncPlan | None = None
    if request.resolutions is None:
        plan = _fetch_and_plan(config, token_store, root)
    else:
        plan, definitions = _fetch_and_plan_library(config, token_store, root)
    selected_keys: set[str] | None = None
    selected_definitions: set[tuple[str, str]] = set()
    if request.resolutions is not None and definitions is not None:
        skill_hashes = {entry.projection.stable_key: _preview_hash(entry) for entry in plan.entries}
        definition_hashes = {
            (_manifest_kind(entry.projection.library_kind), entry.projection.stable_key): (
                _definition_preview_hash(entry)
            )
            for entry in definitions.entries
        }
        for resolution in request.resolutions:
            expected = (
                skill_hashes.get(resolution.stable_key)
                if resolution.kind is SkillLibraryKind.SKILL
                else definition_hashes.get((resolution.kind.value, resolution.stable_key))
            )
            if expected is None or resolution.preview_hash != expected:
                raise _error(
                    LocalErrorCode.INVALID_REQUEST,
                    "Skill versions changed since preview; compare them again before applying.",
                    ComponentId.DAEMON,
                    retryable=False,
                )
        library_choices = [r for r in request.resolutions if r.choice == "library"]
        selected_keys = {r.stable_key for r in library_choices if r.kind is SkillLibraryKind.SKILL}
        selected_definitions = {
            (r.kind.value, r.stable_key)
            for r in library_choices
            if r.kind is not SkillLibraryKind.SKILL
        }
    selected_plan = (
        plan
        if selected_keys is None
        else replace(
            plan,
            entries=tuple(
                entry for entry in plan.entries if entry.projection.stable_key in selected_keys
            ),
            retired=(),
        )
    )
    overwrite = request.overwrite or selected_keys is not None
    remaining = (
        plan
        if selected_keys is None
        else replace(
            plan,
            entries=tuple(
                entry for entry in plan.entries if entry.projection.stable_key not in selected_keys
            ),
        )
    )

    def is_selected_definition(entry: DefinitionPlanEntry) -> bool:
        identity = (_manifest_kind(entry.projection.library_kind), entry.projection.stable_key)
        return identity in selected_definitions

    selected_definition_plan = (
        None
        if definitions is None
        else replace(
            definitions,
            entries=tuple(e for e in definitions.entries if is_selected_definition(e)),
            retired=(),
        )
    )
    remaining_definitions = (
        None
        if definitions is None
        else replace(
            definitions,
            entries=tuple(e for e in definitions.entries if not is_selected_definition(e)),
        )
    )
    conflict_keys = [_target_label(plan, target) for target in remaining.locally_modified]
    if remaining_definitions is not None:
        conflict_keys.extend(
            _target_label(remaining_definitions, target)
            for target in remaining_definitions.locally_modified
        )
    added: list[str] = []
    updated: list[str] = []

    for target in selected_plan.missing:
        added.append(_target_label(plan, target))
    for target in selected_plan.outdated:
        updated.append(_target_label(plan, target))
    if overwrite:
        updated.extend(_target_label(plan, target) for target in selected_plan.locally_modified)
        if selected_keys is None:
            conflict_keys = []
    if selected_definition_plan is not None:
        added.extend(
            _target_label(selected_definition_plan, t) for t in selected_definition_plan.missing
        )
        updated.extend(
            _target_label(selected_definition_plan, t)
            for t in (
                *selected_definition_plan.outdated,
                *selected_definition_plan.locally_modified,
            )
        )
    enabled = auto_sync_enabled(config, data_root)

    snapshot = _sync_paths((plan,) if definitions is None else (plan, definitions))
    try:
        result = apply_skill_sync(plan, overwrite=overwrite, selected_keys=selected_keys)
        if definitions is not None:
            definition_result = apply_definition_sync(
                definitions, overwrite=True, selected=selected_definitions
            )
            result = replace(
                result,
                written=(*result.written, *definition_result.written),
                backups=(*result.backups, *definition_result.backups),
            )
    except SkillSyncConflictError as exc:
        _restore_after_failure(snapshot)
        _LOGGER.warning("skills.apply: conflicts prevented overwrite (%s)", exc)
        status = SkillsSyncStatus(
            state=SkillSyncStatusState.CONFLICTS,
            last_check=datetime.now(UTC),
            conflicts=conflict_keys,
            auto_sync_enabled=enabled,
        )
        if data_root is not None:
            _save_status(data_root, status)
        raise _error(
            LocalErrorCode.INVALID_REQUEST,
            "Locally modified skill files would be overwritten; resolve conflicts first.",
            ComponentId.DAEMON,
            retryable=False,
        ) from exc

    except (SkillSyncError, OSError, ValueError) as exc:
        _restore_after_failure(snapshot)
        raise _error(
            LocalErrorCode.INVALID_REQUEST,
            "The skill plan could not be applied safely; compare the versions again.",
            ComponentId.DAEMON,
            retryable=False,
        ) from exc

    state = SkillSyncStatusState.UPDATED if (added or updated) else SkillSyncStatusState.UP_TO_DATE
    if conflict_keys:
        state = SkillSyncStatusState.CONFLICTS
    elif selected_keys is not None and (
        remaining.missing
        or remaining.outdated
        or (
            remaining_definitions is not None
            and (remaining_definitions.missing or remaining_definitions.outdated)
        )
    ):
        state = SkillSyncStatusState.NOT_SYNCED
    previous = _load_status(data_root) if data_root is not None else None
    successful_sync = (
        datetime.now(UTC)
        if state in {SkillSyncStatusState.UPDATED, SkillSyncStatusState.UP_TO_DATE}
        else previous.last_successful_sync
        if previous is not None
        else None
    )
    status = SkillsSyncStatus(
        state=state,
        last_successful_sync=successful_sync,
        last_check=datetime.now(UTC),
        added=added,
        updated=updated,
        conflicts=conflict_keys,
        error_message=None,
        auto_sync_enabled=enabled,
    )
    if data_root is not None:
        _save_status(data_root, status)

    return SkillsApplyResult(
        written=[str(p) for p in result.written],
        backups=[str(p) for p in result.backups],
        manifest_path=str(result.manifest_path),
        added=added,
        updated=updated,
        conflicts=conflict_keys,
        applied_at=datetime.now(UTC),
    )


def skills_status(
    config: ClientConfig,
    token_store: TokenStore,
    *,
    home: Path | None = None,
    data_root: Path | None = None,
) -> SkillsSyncStatus:
    """Return the persisted synchronization status, refreshing if stale."""
    persisted = _load_status(data_root) if data_root is not None else None
    if persisted is not None:
        return persisted
    # Fallback: compute current state without persisting
    try:
        plan = _fetch_and_plan(config, token_store, home if home is not None else Path.home())
        if plan.missing or plan.outdated or plan.retired:
            state = SkillSyncStatusState.UPDATED
        elif plan.locally_modified:
            state = SkillSyncStatusState.CONFLICTS
        else:
            state = SkillSyncStatusState.UP_TO_DATE
    except LocalFeatureError as exc:
        if exc.error.retryable:
            state = SkillSyncStatusState.NOT_SYNCED
        else:
            state = SkillSyncStatusState.NOT_SYNCED
    except Exception:  # noqa: BLE001
        state = SkillSyncStatusState.NOT_SYNCED
    return SkillsSyncStatus(
        state=state,
        last_check=datetime.now(UTC),
        auto_sync_enabled=auto_sync_enabled(config, data_root),
    )


def auto_sync_enabled(config: ClientConfig, data_root: Path | None = None) -> bool:
    """The local setting wins over the configuration default."""
    if data_root is not None:
        try:
            payload = json.loads((data_root / _SETTINGS_FILE_NAME).read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("auto_sync"), bool):
                return bool(payload["auto_sync"])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    return getattr(config, "skills_auto_sync", True)


def configure_skills(
    config: ClientConfig,
    token_store: TokenStore,
    request: SkillsConfigureRequest,
    *,
    home: Path,
    data_root: Path,
) -> SkillsSyncStatus:
    """Persist the auto-sync setting; enabling starts a synchronization now."""
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / _SETTINGS_FILE_NAME).write_text(
        json.dumps({"auto_sync": request.auto_sync}), encoding="utf-8"
    )
    if not request.auto_sync:
        status = SkillsSyncStatus(
            state=SkillSyncStatusState.DISABLED,
            last_check=datetime.now(UTC),
            auto_sync_enabled=False,
        )
        _save_status(data_root, status)
        return status
    start_auto_sync(config, token_store, home, data_root)
    return SkillsSyncStatus(
        state=SkillSyncStatusState.IN_PROGRESS,
        last_check=datetime.now(UTC),
        auto_sync_enabled=True,
    )


class _AutoSyncRunner:
    """Runs the automatic skill synchronization in a background thread after
    the daemon is fully started. Ensures no startup delay and no blocking
    errors."""

    def __init__(
        self,
        config: ClientConfig,
        token_store: TokenStore,
        home: Path,
        data_root: Path,
    ) -> None:
        self.config = config
        self.token_store = token_store
        self.home = home
        self.data_root = data_root
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            if not auto_sync_enabled(self.config, self.data_root):
                _save_status(
                    self.data_root,
                    SkillsSyncStatus(
                        state=SkillSyncStatusState.DISABLED,
                        last_check=datetime.now(UTC),
                        auto_sync_enabled=False,
                    ),
                )
                return
            self._started = True
            self._thread = threading.Thread(
                target=self._run, name="studio-skills-auto-sync", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        _LOGGER.info("Starting automatic skill synchronization")
        _save_status(
            self.data_root,
            SkillsSyncStatus(
                state=SkillSyncStatusState.IN_PROGRESS,
                last_check=datetime.now(UTC),
                auto_sync_enabled=True,
            ),
        )
        try:
            projections = _fetch_projections(self.config, self.token_store)
            skill_plan, definition_plan = plan_library_sync(self.home, projections)
            plans: tuple[SkillSyncPlan | DefinitionSyncPlan, ...] = (
                skill_plan,
                definition_plan,
            )
            conflict_keys = [
                _target_label(plan, target) for plan in plans for target in plan.locally_modified
            ]
            added: list[str] = []
            updated: list[str] = []
            retired = False

            for plan in plans:
                for target in plan.missing:
                    added.append(_target_label(plan, target))
                for target in plan.outdated:
                    updated.append(_target_label(plan, target))
                retired = retired or bool(plan.retired)

            if conflict_keys:
                _LOGGER.info(
                    "Auto-sync found %d locally modified file(s), skipping",
                    len(conflict_keys),
                )
                status = SkillsSyncStatus(
                    state=SkillSyncStatusState.CONFLICTS,
                    last_check=datetime.now(UTC),
                    conflicts=conflict_keys,
                    auto_sync_enabled=True,
                )
                _save_status(self.data_root, status)
                return

            if not added and not updated and not retired:
                _LOGGER.info("Auto-sync: library already up to date")
                status = SkillsSyncStatus(
                    state=SkillSyncStatusState.UP_TO_DATE,
                    last_successful_sync=datetime.now(UTC),
                    last_check=datetime.now(UTC),
                    auto_sync_enabled=True,
                )
                _save_status(self.data_root, status)
                return

            backups = 0
            snapshot = _sync_paths(plans)
            try:
                if skill_plan.missing or skill_plan.outdated or skill_plan.retired:
                    backups += len(apply_skill_sync(skill_plan, overwrite=False).backups)
                if definition_plan.missing or definition_plan.outdated or definition_plan.retired:
                    backups += len(apply_definition_sync(definition_plan, overwrite=False).backups)
            except Exception:
                try:
                    _restore_paths(snapshot)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Auto-sync rollback failed")
                raise
            _LOGGER.info(
                "Auto-sync completed: added %d, updated %d, backups %d",
                len(added),
                len(updated),
                backups,
            )
            status = SkillsSyncStatus(
                state=SkillSyncStatusState.UPDATED,
                last_successful_sync=datetime.now(UTC),
                last_check=datetime.now(UTC),
                added=added,
                updated=updated,
                conflicts=[],
                error_message=None,
                auto_sync_enabled=True,
            )
            _save_status(self.data_root, status)
        except LocalFeatureError as exc:
            if exc.error.retryable:
                _LOGGER.warning("Auto-sync: library unreachable, will retry on next start")
                status = SkillsSyncStatus(
                    state=SkillSyncStatusState.NOT_SYNCED,
                    last_check=datetime.now(UTC),
                    error_message="Library unreachable; will retry on next start",
                    auto_sync_enabled=True,
                )
            else:
                _LOGGER.warning("Auto-sync: non-retryable error: %s", exc.error.message)
                status = SkillsSyncStatus(
                    state=SkillSyncStatusState.NOT_SYNCED,
                    last_check=datetime.now(UTC),
                    error_message=exc.error.message,
                    auto_sync_enabled=True,
                )
            _save_status(self.data_root, status)
        except SkillSyncConflictError as exc:
            _LOGGER.warning("Auto-sync: conflicts during apply: %s", exc)
            status = SkillsSyncStatus(
                state=SkillSyncStatusState.CONFLICTS,
                last_check=datetime.now(UTC),
                error_message="Locally modified files prevent auto-sync",
                auto_sync_enabled=True,
            )
            _save_status(self.data_root, status)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Auto-sync failed unexpectedly")
            status = SkillsSyncStatus(
                state=SkillSyncStatusState.NOT_SYNCED,
                last_check=datetime.now(UTC),
                error_message="Unexpected error during auto-sync",
                auto_sync_enabled=True,
            )
            _save_status(self.data_root, status)


def start_auto_sync(
    config: ClientConfig,
    token_store: TokenStore,
    home: Path,
    data_root: Path,
) -> _AutoSyncRunner:
    """Start the automatic skill synchronization background task."""
    runner = _AutoSyncRunner(config, token_store, home, data_root)
    runner.start()
    return runner
