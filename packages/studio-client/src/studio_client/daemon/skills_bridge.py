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
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from studio_contracts.library import (
    LibraryActivate,
    LibraryDeprecate,
    LibraryKind,
    LibraryResource,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersionCreate,
    LibraryVersionRef,
)
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
from studio_client.errors import AuthenticationError, RateLimitError, StudioApiError
from studio_client.projection_backups import (
    ProjectionBackup,
    commit_projection_backup,
    prepare_projection_backup,
)
from studio_client.skill_sync import (
    _STABLE_KEY_RE,
    _WINDOWS_RESERVED_NAMES,
    GLOBAL_PROJECTION_SCOPES,
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

_SKILL_LIMIT = 500

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
_GLOBAL_SCOPES = GLOBAL_PROJECTION_SCOPES


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
    limit: int = 500,
    selection: dict[str, set[str]] | None = None,
) -> tuple[LibraryContextItem, ...]:
    provider = LibraryContextProvider(api)
    textual = await provider.fetch(
        project_id,
        limit=limit,
        kinds=("rule", "skill"),
        stable_keys=selection,
    )
    items = [item for item in textual.items if item.scope in _GLOBAL_SCOPES]

    for row in await provider.fetch_effective_versions(
        project_id,
        kind="agent_definition",
        limit=limit,
        stable_keys=(selection or {}).get("agent_definition"),
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
    journal_sink: list[ProjectionBackup] | None = None,
) -> SkillSyncResult:
    if selected is not None:
        if not selected:
            return SkillSyncResult(
                written=(), backups=(), manifest_path=plan.manifest_path, removed=()
            )
        plan = _select_definitions(plan, selected)
    conflicts = tuple(plan.locally_modified)
    skipped_paths = {target.path for target in conflicts} if not overwrite else set()
    _verify_definition_plan_is_fresh(plan)

    desired: dict[Path, str | None] = {
        target.path: target.desired_text
        for entry in plan.entries
        for target in entry.all_targets
        if target.state != "current" and target.path not in skipped_paths
    }
    desired.update({target.path: None for target in plan.retired})
    desired[plan.manifest_path] = plan.manifest_text
    journal = prepare_projection_backup(plan.home, desired)
    _verify_definition_plan_is_fresh(plan)

    backup_root: Path | None = None
    backups: list[Path] = []
    if conflicts and overwrite:
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
            if target.state == "current" or target.path in skipped_paths:
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
    if journal_sink is None:
        commit_projection_backup(journal)
    elif journal is not None:
        journal_sink.append(journal)
    return SkillSyncResult(
        written=tuple(written),
        backups=tuple(backups),
        manifest_path=plan.manifest_path,
        removed=tuple(removed),
        conflicts=tuple(target.path for target in conflicts) if not overwrite else (),
    )


async def revert_override(
    api: Any,
    home: Path,
    library_kind: str,
    stable_key: str,
    *,
    include_opencode: bool = True,
    limit: int = 500,
) -> SkillSyncResult:
    """Drop the caller's User override of one skill, rule or agent definition and
    re-project the common version.

    The override is deprecated, never deleted (it stays in the owner's history);
    the local files are rewritten through the journaled sync, so
    ``library restore`` brings the override text back."""

    rows = await api.list_library_resources(kind=library_kind, limit=limit)
    live = [r for r in rows if r.stable_key == stable_key and str(r.status) == "active"]
    override = next((r for r in live if str(r.scope) == "user"), None)
    if override is None:
        raise SkillSyncError("no active user override for this item")
    if all(str(r.scope) == "user" for r in live):
        raise SkillSyncError("no common version to return to")
    await api.deprecate_library_resource(
        override.id,
        LibraryDeprecate(expected_resource_version=override.version),
        idempotency_key=f"revert-override-{override.id}-{override.version}",
    )
    projections = await fetch_library_projections(api, None, limit=limit)
    journals: list[ProjectionBackup] = []
    if library_kind == "skill":
        skills = [i for i in projections if i.library_kind == "skill"]
        result = apply_skill_sync(
            plan_skill_sync(home, skills, include_opencode=include_opencode),
            overwrite=True,
            selected_keys={stable_key},
            journal_sink=journals,
        )
    else:
        definitions = [i for i in projections if i.library_kind in _DEFINITION_KINDS]
        result = apply_definition_sync(
            plan_definition_sync(home, definitions),
            overwrite=True,
            selected={(_manifest_kind(library_kind), stable_key)},
            journal_sink=journals,
        )
    for journal in journals:
        commit_projection_backup(journal)
    return result


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
    except RateLimitError as exc:
        _LOGGER.warning("skills.sync: library rate limited (retry_after=%s)", exc.retry_after)
        wait = f" Retry in about {exc.retry_after}s." if exc.retry_after is not None else ""
        raise _error(
            LocalErrorCode.INTERNAL_ERROR,
            f"The Studio OS Library is rate limiting requests.{wait}",
            ComponentId.DAEMON,
            retryable=True,
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
    config: ClientConfig,
    token_store: TokenStore,
    selection: dict[str, set[str]] | None = None,
) -> tuple[LibraryContextItem, ...]:
    if selection is None:
        return _run_fetch(config, token_store, _fetch)
    return _run_fetch(config, token_store, lambda c, t: _fetch(c, t, selection))


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
    selection: dict[str, set[str]] | None = None,
) -> tuple[SkillSyncPlan, DefinitionSyncPlan]:
    return plan_library_sync(home, _fetch_projections(config, token_store, selection))


async def _fetch(
    config: ClientConfig,
    token_store: TokenStore,
    selection: dict[str, set[str]] | None = None,
) -> Any:
    async with StudioApiClient(config, token_store) as client:
        return await fetch_library_projections(
            client, None, limit=_SKILL_LIMIT, selection=selection
        )


async def _fetch_skills_only(config: ClientConfig, token_store: TokenStore) -> Any:
    async with StudioApiClient(config, token_store) as client:
        return await fetch_skill_projections(client, None, limit=_SKILL_LIMIT)


_STATE_SEVERITY = {"current": 0, "missing": 1, "outdated": 2, "locally_modified": 3}


def _target_states(entry: SkillPlanEntry) -> list[SkillTargetState]:
    """One state per harness: the worst over SKILL.md and its auxiliary files."""
    worst: dict[str, str] = {}
    for target in entry.all_files:
        previous = worst.get(target.harness, "current")
        worst[target.harness] = max(previous, target.state, key=_STATE_SEVERITY.__getitem__)
    return [
        SkillTargetState(harness=_HARNESS[harness], state=SkillSyncState(state))
        for harness, state in worst.items()
    ]


def summarize(plan: SkillSyncPlan, *, checked_at: datetime | None = None) -> SkillsCheckResult:
    entries = [
        SkillCheckEntry(
            stable_key=entry.projection.stable_key,
            version=entry.projection.version,
            targets=_target_states(entry),
        )
        for entry in plan.entries
    ]
    counts = Counter(target.state for entry in entries for target in entry.targets)
    return SkillsCheckResult(
        skills=entries,
        current=counts[SkillSyncState.CURRENT],
        missing=counts[SkillSyncState.MISSING],
        outdated=counts[SkillSyncState.OUTDATED],
        locally_modified=counts[SkillSyncState.LOCALLY_MODIFIED],
        in_sync=not plan.missing and not plan.retired and not plan.drifted,
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


def _selection_from_resolutions(
    resolutions: list[Any],
) -> dict[str, set[str]]:
    selected: dict[str, set[str]] = {}
    for resolution in resolutions:
        kind = resolution.kind.value
        if kind == "agent":
            kind = "agent_definition"
        selected.setdefault(kind, set()).add(resolution.stable_key)
    return selected


_PUBLISH_KINDS: dict[str, LibraryKind] = {
    "skill": LibraryKind.SKILL,
    "rule": LibraryKind.RULE,
    "agent": LibraryKind.AGENT_DEFINITION,
}
"""Manifest kind (`agent`) to the Library kind it overrides
(`agent_definition`). Publication only ever targets the three kinds the skill
synchronization projects."""

_PROVENANCE_PREFIX = "<!-- studio-os-library:"


@dataclass(frozen=True)
class OverrideDraft:
    """One locally modified file to publish as the caller's personal version.

    Carries the local content only: the common base is resolved over HTTP at
    publication time, by the server that owns the precedence rules."""

    kind: str
    stable_key: str
    title: str
    description: str | None
    text: str
    projection: LibraryContextItem


def split_local_override(text: str) -> tuple[str | None, str]:
    """Inverse of the projection renderers: `(description, body)` of a file.

    Drops the generated YAML frontmatter and the Studio OS provenance comment
    so the published version stores the user's prose, never the projection
    marker of the previous version."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    description: str | None = None
    if normalized.startswith("---\n"):
        end = normalized.find("\n---\n", 4)
        if end != -1:
            for line in normalized[4:end].splitlines():
                name, separator, raw = line.partition(":")
                if separator and name.strip() == "description":
                    try:
                        parsed = json.loads(raw.strip())
                    except json.JSONDecodeError:
                        parsed = raw.strip()
                    if isinstance(parsed, str) and parsed.strip():
                        description = " ".join(parsed.split())
            normalized = normalized[end + 5 :]
    lines = normalized.splitlines(keepends=True)
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith(_PROVENANCE_PREFIX)):
        lines.pop(0)
    return description, "".join(lines).strip("\n")


def _locally_modified_text(
    targets: Sequence[SkillTargetPlan | DefinitionTargetPlan],
) -> str | None:
    """The user's own copy that the publication must capture (main file only)."""
    for target in targets:
        if target.state == "locally_modified" and target.current_text:
            return target.current_text
    return None


def _override_draft(
    kind: str, projection: LibraryContextItem, local_text: str | None
) -> OverrideDraft:
    description, text = split_local_override(local_text or "")
    if local_text is None or not text.strip():
        raise _error(
            LocalErrorCode.INVALID_REQUEST,
            "Only a locally modified file with content can be published as an override.",
            ComponentId.DAEMON,
            retryable=False,
        )
    return OverrideDraft(
        kind=kind,
        stable_key=projection.stable_key,
        title=projection.title,
        description=description or projection.description,
        text=text,
        projection=projection,
    )


def override_drafts(
    plan: SkillSyncPlan,
    definitions: DefinitionSyncPlan,
    resolutions: list[Any],
) -> list[OverrideDraft]:
    """One draft per `publish` resolution, in resolution order."""
    wanted = {
        (resolution.kind.value, resolution.stable_key)
        for resolution in resolutions
        if resolution.choice == "publish"
    }
    drafts: dict[tuple[str, str], OverrideDraft] = {}
    for skill_entry in plan.entries:
        identity = ("skill", skill_entry.projection.stable_key)
        if identity in wanted:
            drafts[identity] = _override_draft(
                "skill",
                skill_entry.projection,
                _locally_modified_text(skill_entry.all_targets),
            )
    for definition_entry in definitions.entries:
        kind = _manifest_kind(definition_entry.projection.library_kind)
        identity = (kind, definition_entry.projection.stable_key)
        if identity in wanted:
            drafts[identity] = _override_draft(
                kind,
                definition_entry.projection,
                _locally_modified_text(definition_entry.targets),
            )
    missing = [
        (resolution.kind.value, resolution.stable_key)
        for resolution in resolutions
        if resolution.choice == "publish"
        and (resolution.kind.value, resolution.stable_key) not in drafts
    ]
    if missing:
        raise _error(
            LocalErrorCode.INVALID_REQUEST,
            "A published choice names an item this machine does not compare; compare again.",
            ComponentId.DAEMON,
            retryable=False,
        )
    return [
        drafts[(resolution.kind.value, resolution.stable_key)]
        for resolution in resolutions
        if resolution.choice == "publish"
    ]


def _override_content(draft: OverrideDraft, base: dict[str, Any] | None) -> dict[str, Any]:
    """The common version as a template, with the user's local prose in it.

    Keeping the common `content_schema` preserves every other field the
    schema allows (`applies_to`, skill files, agent instructions) while the
    free prose becomes the caller's own."""
    content: dict[str, Any] = (
        dict(base) if base else {"content_schema": draft.projection.content_schema}
    )
    if draft.kind == "skill":
        content.setdefault(
            "files",
            [
                {
                    "path": path,
                    "text": text,
                    "sha256": sha256(text.encode("utf-8")).hexdigest(),
                }
                for path, text in draft.projection.files
            ],
        )
        if content["content_schema"].endswith("/v2") or "disable_model_invocation" in content:
            content.setdefault(
                "disable_model_invocation", draft.projection.disable_model_invocation
            )
        content["text"] = draft.text
    elif draft.kind == "agent":
        summary, _, rest = draft.text.partition("\n\n")
        content["summary"] = summary.strip() or None
        content["intended_use"] = rest.strip() or None
        content.pop("text", None)
    else:
        content["text"] = draft.text
    return content


async def _find_library_resource(
    client: StudioApiClient,
    kind: LibraryKind,
    stable_key: str,
    scope: LibraryScope,
) -> LibraryResource | None:
    offset = 0
    while True:
        page = await client.list_library_resources(
            kind=kind.value, scope=scope.value, limit=_SKILL_LIMIT, offset=offset
        )
        for resource in page:
            if resource.stable_key == stable_key:
                return resource
        if len(page) < _SKILL_LIMIT:
            return None
        offset += _SKILL_LIMIT


async def _base_version_content(
    client: StudioApiClient, resource: LibraryResource | None
) -> dict[str, Any] | None:
    if resource is None or resource.active_version <= 0:
        return None
    result = await client.batch_library_versions([(resource.id, resource.active_version)])
    detail = result.items[0].detail if result.items else None
    return dict(detail.content) if detail is not None else None


async def _publish_override(client: StudioApiClient, draft: OverrideDraft) -> None:
    """Publish the local content as the caller's `user`-scope version, active.

    Reuses the existing override publication surface (create resource with
    `derived_from`, or a new version of the caller's own override, then
    activation). The row stays private: the server only ever lists it for its
    owner, so no other user sees or receives it."""
    kind = _PUBLISH_KINDS[draft.kind]
    common = await _find_library_resource(client, kind, draft.stable_key, LibraryScope.STUDIO)
    content = _override_content(draft, await _base_version_content(client, common))
    derived_from = (
        LibraryVersionRef(resource_id=common.id, version=common.active_version)
        if common is not None and common.active_version > 0
        else None
    )
    mine = await _find_library_resource(client, kind, draft.stable_key, LibraryScope.USER)
    if mine is None:
        mine = await client.create_library_resource(
            LibraryResourceCreate(
                kind=kind,
                stable_key=draft.stable_key,
                scope=LibraryScope.USER,
                title=draft.title,
                description=draft.description,
                content=content,
                derived_from=derived_from,
            ),
            idempotency_key=str(uuid4()),
        )
        version = 1
    else:
        current = await client.get_library_resource(mine.id)
        if current.active_version > 0 and await _base_version_content(client, current) == content:
            return
        created = await client.create_library_version(
            current.id,
            LibraryVersionCreate(
                title=draft.title,
                description=draft.description,
                content=content,
                derived_from=derived_from,
            ),
            idempotency_key=str(uuid4()),
        )
        version = created.version
        mine = current
    current = await client.get_library_resource(mine.id)
    if current.active_version != version:
        await client.activate_library_version(
            current.id,
            LibraryActivate(version=version, expected_resource_version=current.version),
            idempotency_key=str(uuid4()),
        )


async def _publish_overrides(
    config: ClientConfig, token_store: TokenStore, drafts: list[OverrideDraft]
) -> tuple[LibraryContextItem, ...]:
    async with StudioApiClient(config, token_store) as client:
        for draft in drafts:
            await _publish_override(client, draft)
    return ()


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
    seen: set[tuple[str | None, str]] = set()
    for target in entry.all_targets:
        if target.state == "current":
            continue
        if target.state != "missing":
            if (target.current_text, target.desired_text) in seen:
                continue
            seen.add((target.current_text, target.desired_text))
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
    selection: dict[str, list[str]] | None = None,
) -> SkillsPreviewResult:
    """Return a preview (unified diff) of the skill, rule and agent synchronization plan."""
    plan, definitions = _fetch_and_plan_library(
        config,
        token_store,
        home if home is not None else Path.home(),
        {kind: set(keys) for kind, keys in selection.items()} if selection is not None else None,
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
    skill_targets = (*plan.current, *plan.missing, *plan.outdated, *plan.locally_modified)
    counts = Counter(target.state for target in skill_targets)
    return SkillsPreviewResult(
        skills=entries,
        current=counts["current"],
        missing=counts["missing"],
        outdated=counts["outdated"],
        locally_modified=counts["locally_modified"],
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
        plan, definitions = _fetch_and_plan_library(
            config,
            token_store,
            root,
            _selection_from_resolutions(request.resolutions),
        )
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
        if any(resolution.choice == "publish" for resolution in request.resolutions):
            # `publish` writes the local content as the caller's own version
            # first, then the plan is re-read so the applied content and the
            # recorded sync base are the version that now shadows the common.
            drafts = override_drafts(plan, definitions, request.resolutions)
            _run_fetch(
                config,
                token_store,
                lambda c, t: _publish_overrides(c, t, drafts),
            )
            plan, definitions = _fetch_and_plan_library(
                config,
                token_store,
                root,
                _selection_from_resolutions(request.resolutions),
            )
        library_choices = [r for r in request.resolutions if r.choice in {"library", "publish"}]
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
    journals: list[ProjectionBackup] = []
    try:
        result = apply_skill_sync(
            plan, overwrite=overwrite, selected_keys=selected_keys, journal_sink=journals
        )
        if definitions is not None:
            definition_result = apply_definition_sync(
                definitions, overwrite=True, selected=selected_definitions, journal_sink=journals
            )
            result = replace(
                result,
                written=(*result.written, *definition_result.written),
                backups=(*result.backups, *definition_result.backups),
                conflicts=(*result.conflicts, *definition_result.conflicts),
            )
        for extra in result.conflicts:
            label = str(extra.relative_to(root) if extra.is_absolute() else extra)
            if label not in conflict_keys:
                conflict_keys.append(label)
        for journal in journals:
            commit_projection_backup(journal)
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

            if not added and not updated and not retired:
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
                else:
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
            journals: list[ProjectionBackup] = []
            try:
                if skill_plan.missing or skill_plan.outdated or skill_plan.retired:
                    backups += len(
                        apply_skill_sync(skill_plan, overwrite=False, journal_sink=journals).backups
                    )
                if definition_plan.missing or definition_plan.outdated or definition_plan.retired:
                    backups += len(
                        apply_definition_sync(
                            definition_plan, overwrite=False, journal_sink=journals
                        ).backups
                    )
                for journal in journals:
                    commit_projection_backup(journal)
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
            if conflict_keys:
                status = SkillsSyncStatus(
                    state=SkillSyncStatusState.CONFLICTS,
                    last_check=datetime.now(UTC),
                    added=added,
                    updated=updated,
                    conflicts=conflict_keys,
                    error_message=None,
                    auto_sync_enabled=True,
                )
            else:
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


def mark_update_pending(
    config: ClientConfig,
    token_store: TokenStore,
    home: Path,
    data_root: Path,
) -> bool:
    """Plan the library sync without writing any projection and record an
    `update_pending` status when the library differs from this machine."""
    plans = plan_library_sync(home, _fetch_projections(config, token_store))
    added = [_target_label(plan, target) for plan in plans for target in plan.missing]
    updated = [_target_label(plan, target) for plan in plans for target in plan.outdated]
    if not added and not updated and not any(plan.retired for plan in plans):
        return False
    previous = _load_status(data_root)
    _save_status(
        data_root,
        SkillsSyncStatus(
            state=SkillSyncStatusState.UPDATE_PENDING,
            last_successful_sync=previous.last_successful_sync if previous else None,
            last_check=datetime.now(UTC),
            added=added,
            updated=updated,
            conflicts=[
                _target_label(plan, target) for plan in plans for target in plan.locally_modified
            ],
            auto_sync_enabled=auto_sync_enabled(config, data_root),
        ),
    )
    return True
