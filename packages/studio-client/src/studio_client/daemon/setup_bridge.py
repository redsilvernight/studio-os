"""``setup.plan`` / ``setup.apply``: the Desktop « Configurer ce poste » action.

No second engine: hooks, guard and OpenCode plugin come from ``machine_setup``
(the ``setup-hooks`` templates), skills from ``skill_sync``, adapter drift from
``adapters_check``. ``setup.plan`` never writes. ``setup.apply`` is bound to a
previewed plan (id + hash + explicit confirmation); a differing file is replaced
only when named, after a backup, and every write is read back before it is
reported. The MCP wiring stays on the AIB-E ``harness.*`` commands.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.machine_setup import (
    SetupAdaptersState,
    SetupAdaptersStep,
    SetupApplyRequest,
    SetupApplyResult,
    SetupHarness,
    SetupItemKind,
    SetupItemOutcome,
    SetupItemPlan,
    SetupItemResult,
    SetupItemState,
    SetupPlan,
    SetupSkillsOutcome,
    SetupSkillsResult,
    SetupSkillsState,
    SetupSkillsStep,
    SetupUnavailableReason,
)

from studio_client.adapters_check import check_adapters, has_canonical_definitions
from studio_client.config import ClientConfig
from studio_client.daemon import skills_bridge
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.errors import AuthenticationError, StudioApiError
from studio_client.hooks import HARNESSES
from studio_client.machine_setup import (
    SetupHooksPlan,
    apply_hooks,
    apply_skills,
    detected_harnesses,
    plan_fingerprint,
    plan_hooks,
)
from studio_client.skill_sync import (
    SkillSyncConflictError,
    SkillSyncError,
    SkillSyncPlan,
    plan_skill_sync,
)
from studio_client.tokens import TokenStore, origin_of

_LOGGER = logging.getLogger("studio_client.daemon.setup_bridge")

PLAN_TTL = timedelta(minutes=10)
MAX_STORED_PLANS = 4


@dataclass(frozen=True)
class _StoredPlan:
    plan: SetupPlan
    hooks: SetupHooksPlan
    skills: SkillSyncPlan | None


class _SkillsUnavailable(Exception):
    def __init__(self, reason: SetupUnavailableReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def _error(code: LocalErrorCode, message: str, *, retryable: bool = False) -> LocalFeatureError:
    return LocalFeatureError(
        LocalError(code=code, message=message, component=ComponentId.DAEMON, retryable=retryable)
    )


def _path_dirs() -> Sequence[str]:
    return tuple(part for part in os.environ.get("PATH", "").split(os.pathsep) if part)


def _skills_fingerprint(plan: SkillSyncPlan | None) -> str:
    if plan is None:
        return "-"
    digest = hashlib.sha256()
    for entry in plan.entries:
        digest.update(
            f"{entry.projection.stable_key}|{entry.projection.version}|{entry.sha256}".encode()
        )
        for target in entry.targets:
            digest.update(f"|{target.state}|{target.current_sha256}".encode())
        digest.update(b"\n")
    return digest.hexdigest()


class SetupBridge:
    """Plan store + apply for the workstation setup. ``home``, ``roots`` and
    ``path_dirs`` are injected so the daemon resolves them, never the Desktop."""

    def __init__(
        self,
        config: ClientConfig,
        token_store: TokenStore,
        *,
        home: Callable[[], Path] = Path.home,
        roots: Callable[[], Sequence[Path]] = lambda: (),
        path_dirs: Callable[[], Sequence[str]] = _path_dirs,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._token_store = token_store
        self._home = home
        self._roots = roots
        self._path_dirs = path_dirs
        self._clock = clock
        self._plans: dict[str, _StoredPlan] = {}
        self._lock = threading.Lock()

    # -- plan -------------------------------------------------------------

    def plan(self) -> SetupPlan:
        home = self._home()
        detected = detected_harnesses(home, self._path_dirs())
        hooks = plan_hooks(home, detected)
        skills_step, skills_plan = self._plan_skills(home)
        created = self._clock()
        digest = hashlib.sha256()
        digest.update(plan_fingerprint(hooks).encode())
        digest.update(_skills_fingerprint(skills_plan).encode())
        names = {spec.harness for spec in detected}
        plan = SetupPlan(
            plan_id=f"setup-{uuid4().hex[:16]}",
            plan_hash=digest.hexdigest(),
            created_at=created,
            expires_at=created + PLAN_TTL,
            harnesses=[
                SetupHarness(harness=spec.harness, detected=spec.harness in names)
                for spec in HARNESSES
            ],
            hooks=[
                SetupItemPlan(
                    item_id=item.item_id,
                    kind=SetupItemKind(item.kind),
                    harness=item.harness,
                    state=SetupItemState(item.state),
                    managed=item.managed,
                    lines_added=item.lines_added,
                    lines_removed=item.lines_removed,
                    diff=item.diff,
                    diff_truncated=item.diff_truncated,
                    needs_registration=item.needs_registration,
                )
                for item in hooks.items
            ],
            skills=skills_step,
            adapters=self._check_adapters(),
        )
        with self._lock:
            self._forget_expired()
            if len(self._plans) >= MAX_STORED_PLANS:
                oldest = min(self._plans, key=lambda key: self._plans[key].plan.created_at)
                del self._plans[oldest]
            self._plans[plan.plan_id] = _StoredPlan(plan, hooks, skills_plan)
        return plan

    def _forget_expired(self) -> None:
        now = self._clock()
        for plan_id in [k for k, v in self._plans.items() if v.plan.expires_at <= now]:
            del self._plans[plan_id]

    def _load_projections(self) -> Any:
        if not self._token_store.get_token(origin_of(self._config.api_base_url)):
            raise _SkillsUnavailable(SetupUnavailableReason.NOT_SIGNED_IN)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run, skills_bridge._fetch(self._config, self._token_store)
                ).result()
        except AuthenticationError as exc:
            raise _SkillsUnavailable(SetupUnavailableReason.CREDENTIAL_REJECTED) from exc
        except StudioApiError as exc:
            _LOGGER.warning("setup.plan: library unreachable (%s)", type(exc).__name__)
            raise _SkillsUnavailable(SetupUnavailableReason.LIBRARY_UNREACHABLE) from exc

    def _plan_skills(self, home: Path) -> tuple[SetupSkillsStep, SkillSyncPlan | None]:
        try:
            projections = self._load_projections()
            plan = plan_skill_sync(home, projections)
        except _SkillsUnavailable as exc:
            return SetupSkillsStep(state=SetupSkillsState.UNAVAILABLE, reason=exc.reason), None
        except SkillSyncError as exc:
            _LOGGER.warning("setup.plan: invalid library skill (%s)", type(exc).__name__)
            return (
                SetupSkillsStep(
                    state=SetupSkillsState.UNAVAILABLE,
                    reason=SetupUnavailableReason.INVALID_SKILL,
                ),
                None,
            )
        step = SetupSkillsStep(
            state=SetupSkillsState.CHECKED,
            current=len(plan.current),
            missing=len(plan.missing),
            outdated=len(plan.outdated),
            locally_modified=len(plan.locally_modified),
        )
        return step, plan

    def _check_adapters(self) -> SetupAdaptersStep:
        roots = [root for root in self._roots() if has_canonical_definitions(root)]
        if not roots:
            return SetupAdaptersStep(state=SetupAdaptersState.NOT_APPLICABLE)
        checked = 0
        drifted = 0
        try:
            for root in roots:
                report = check_adapters(root)
                checked += report.checked
                drifted += len({(f["adapter"], f["key"]) for f in report.failures})
        except (OSError, ValueError) as exc:
            _LOGGER.warning("setup.plan: adapters check failed (%s)", type(exc).__name__)
            return SetupAdaptersStep(state=SetupAdaptersState.UNAVAILABLE, workspaces=len(roots))
        return SetupAdaptersStep(
            state=SetupAdaptersState.CHECKED,
            workspaces=len(roots),
            checked=checked,
            drifted=min(drifted, checked),
        )

    # -- apply ------------------------------------------------------------

    def apply(self, request: SetupApplyRequest) -> SetupApplyResult:
        with self._lock:
            self._forget_expired()
            stored = self._plans.get(request.plan_id)
        if stored is None:
            raise _error(
                LocalErrorCode.PLAN_EXPIRED, "The plan is unknown or has expired; preview again."
            )
        if request.plan_hash != stored.plan.plan_hash:
            raise _error(
                LocalErrorCode.INVALID_REQUEST,
                "The confirmation does not match the previewed plan.",
            )
        differing = {
            item.item_id for item in stored.plan.hooks if item.state is SetupItemState.DIFFERS
        }
        unknown = set(request.overwrite_items) - differing
        if unknown:
            raise _error(
                LocalErrorCode.INVALID_REQUEST,
                "Only a differing file of the previewed plan can be named for replacement.",
            )
        hooks = apply_hooks(stored.hooks, overwrite=frozenset(request.overwrite_items))
        skills = self._apply_skills(stored, request.sync_skills)
        with self._lock:
            self._plans.pop(request.plan_id, None)
        results = [
            SetupItemResult(
                item_id=item.item_id,
                outcome=SetupItemOutcome(item.outcome),
                backed_up=item.backed_up,
            )
            for item in hooks.items
        ]
        return SetupApplyResult(
            plan_id=request.plan_id,
            hooks=results,
            skills=skills,
            backups_created=any(item.backed_up for item in results),
        )

    def _apply_skills(self, stored: _StoredPlan, sync: bool) -> SetupSkillsResult:
        plan = stored.skills
        if plan is None:
            return SetupSkillsResult(outcome=SetupSkillsOutcome.UNAVAILABLE)
        left_modified = len(plan.locally_modified)
        if not sync:
            return SetupSkillsResult(
                outcome=SetupSkillsOutcome.SKIPPED, left_modified=left_modified
            )
        try:
            result = apply_skills(plan)
        except SkillSyncConflictError:
            # A skill file changed since the preview: nothing is clobbered.
            return SetupSkillsResult(
                outcome=SetupSkillsOutcome.SKIPPED, left_modified=left_modified
            )
        except (SkillSyncError, OSError) as exc:
            _LOGGER.warning("setup.apply: skills sync failed (%s)", type(exc).__name__)
            return SetupSkillsResult(outcome=SetupSkillsOutcome.FAILED, left_modified=left_modified)
        if result is None:
            return SetupSkillsResult(
                outcome=SetupSkillsOutcome.UNCHANGED, left_modified=left_modified
            )
        expected = {
            target.path: entry.rendered for entry in plan.entries for target in entry.targets
        }
        confirmed = all(_read_equals(path, expected.get(path)) for path in result.written)
        if not confirmed or not result.written:
            return SetupSkillsResult(outcome=SetupSkillsOutcome.FAILED, left_modified=left_modified)
        return SetupSkillsResult(
            outcome=SetupSkillsOutcome.SYNCED,
            written=len(result.written),
            left_modified=left_modified,
        )


def _read_equals(path: Path, expected: str | None) -> bool:
    if expected is None:
        return False
    try:
        return path.read_text(encoding="utf-8") == expected
    except (OSError, UnicodeDecodeError):
        return False


__all__ = ["MAX_STORED_PLANS", "PLAN_TTL", "SetupBridge"]
