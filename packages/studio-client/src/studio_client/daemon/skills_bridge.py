"""Bridge commands for skills synchronization.

Provides ``skills.check`` (read-only), ``skills.preview`` (diff), ``skills.apply``
(apply with confirmation), and ``skills.status`` (persisted sync status).
Auto-sync at daemon startup is orchestrated from ``daemon.runtime``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.skills import (
    SkillCheckEntry,
    SkillHarnessTarget,
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
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.errors import AuthenticationError, StudioApiError
from studio_client.skill_sync import (
    SkillSyncConflictError,
    SkillSyncError,
    SkillSyncPlan,
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


def _status_path(data_root: Path) -> Path:
    return data_root / _STATUS_FILE_NAME


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


def _fetch_and_plan(
    config: ClientConfig,
    token_store: TokenStore,
    home: Path,
) -> SkillSyncPlan:
    """Fetch projections and build a sync plan. Raises LocalFeatureError on failure."""
    if not token_store.get_token(origin_of(config.api_base_url)):
        raise _error(
            LocalErrorCode.SECRET_ABSENT,
            "No machine credential is stored.",
            ComponentId.SECRET_STORE,
            retryable=False,
        )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            projections = pool.submit(asyncio.run, _fetch(config, token_store)).result()
        return plan_skill_sync(home, projections)
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
    except SkillSyncError as exc:
        _LOGGER.warning("skills.sync: invalid library skill (%s)", type(exc).__name__)
        raise _error(
            LocalErrorCode.INTERNAL_ERROR,
            "A Library skill could not be checked.",
            ComponentId.DAEMON,
            retryable=False,
        ) from exc


async def _fetch(config: ClientConfig, token_store: TokenStore) -> Any:
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


def preview_skills(
    config: ClientConfig,
    token_store: TokenStore,
    *,
    home: Path | None = None,
) -> SkillsPreviewResult:
    """Return a preview (unified diff) of the skill synchronization plan."""
    plan = _fetch_and_plan(config, token_store, home if home is not None else Path.home())
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
            diff="",
        )
        for entry in plan.entries
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
    plan = _fetch_and_plan(config, token_store, home if home is not None else Path.home())
    conflicts = list(plan.locally_modified)
    conflict_keys = [target.path.name for target in conflicts] if conflicts else []
    added: list[str] = []
    updated: list[str] = []

    for target in plan.missing:
        added.append(target.path.name)
    for target in plan.outdated:
        updated.append(target.path.name)
    if request.overwrite:
        updated.extend(conflict_keys)
        conflict_keys = []
    enabled = auto_sync_enabled(config, data_root)

    try:
        result = apply_skill_sync(plan, overwrite=request.overwrite)
    except SkillSyncConflictError as exc:
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

    state = SkillSyncStatusState.UPDATED if (added or updated) else SkillSyncStatusState.UP_TO_DATE
    status = SkillsSyncStatus(
        state=state,
        last_successful_sync=datetime.now(UTC),
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
            plan = _fetch_and_plan(self.config, self.token_store, self.home)
            conflicts = list(plan.locally_modified)
            conflict_keys = [target.path.name for target in conflicts] if conflicts else []
            added: list[str] = []
            updated: list[str] = []

            for target in plan.missing:
                added.append(target.path.name)
            for target in plan.outdated:
                updated.append(target.path.name)

            if conflicts:
                _LOGGER.info(
                    "Auto-sync found %d locally modified skill(s), skipping", len(conflicts)
                )
                status = SkillsSyncStatus(
                    state=SkillSyncStatusState.CONFLICTS,
                    last_check=datetime.now(UTC),
                    conflicts=conflict_keys,
                    auto_sync_enabled=True,
                )
                _save_status(self.data_root, status)
                return

            if not added and not updated and not plan.retired:
                _LOGGER.info("Auto-sync: skills already up to date")
                status = SkillsSyncStatus(
                    state=SkillSyncStatusState.UP_TO_DATE,
                    last_successful_sync=datetime.now(UTC),
                    last_check=datetime.now(UTC),
                    auto_sync_enabled=True,
                )
                _save_status(self.data_root, status)
                return

            result = apply_skill_sync(plan, overwrite=False)
            _LOGGER.info(
                "Auto-sync completed: added %d, updated %d, backups %d",
                len(added),
                len(updated),
                len(result.backups),
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
