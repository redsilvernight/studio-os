"""Read-only ``skills.check`` bridge command.

Reuses ``skill_sync.plan_skill_sync`` (the same engine as
``studio-client skills check``) and never writes: the Desktop only learns which
Studio-scope Library skills are current, missing, outdated or locally modified
in the two global harness directories. Neither skill content nor a filesystem
path leaves this module.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.skills import (
    SkillCheckEntry,
    SkillHarnessTarget,
    SkillsCheckResult,
    SkillSyncState,
    SkillTargetState,
)

from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.errors import AuthenticationError, StudioApiError
from studio_client.skill_sync import (
    SkillSyncError,
    SkillSyncPlan,
    fetch_skill_projections,
    plan_skill_sync,
)
from studio_client.tokens import TokenStore, origin_of

_LOGGER = logging.getLogger("studio_client.daemon.skills_bridge")

_SKILL_LIMIT = 100

# The contract stays vendor-neutral: the wire names the two global skill
# directories by role, not by product.
_HARNESS = {
    "agents": SkillHarnessTarget.AGENTS,
    "claude": SkillHarnessTarget.ASSISTANT,
}

SkillFetcher = Callable[[StudioApiClient], Any]


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


def summarize(plan: SkillSyncPlan, *, checked_at: datetime | None = None) -> SkillsCheckResult:
    entries = [
        SkillCheckEntry(
            stable_key=entry.projection.stable_key,
            version=entry.projection.version,
            targets=[
                SkillTargetState(
                    harness=_HARNESS[target.harness], state=SkillSyncState(target.state)
                )
                for target in entry.targets
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
        in_sync=not plan.missing and drifted == 0,
        checked_at=checked_at or datetime.now(UTC),
    )


async def _fetch(config: ClientConfig, token_store: TokenStore) -> Any:
    async with StudioApiClient(config, token_store) as client:
        return await fetch_skill_projections(client, None, limit=_SKILL_LIMIT)


def check_skills(
    config: ClientConfig,
    token_store: TokenStore,
    *,
    home: Path | None = None,
) -> SkillsCheckResult:
    """Compare the effective Library skills with the local harness copies."""
    if not token_store.get_token(origin_of(config.api_base_url)):
        raise _error(
            LocalErrorCode.SECRET_ABSENT,
            "No machine credential is stored.",
            ComponentId.SECRET_STORE,
            retryable=False,
        )
    try:
        # A short-lived worker thread keeps asyncio.run valid whether or not the
        # caller already runs an event loop.
        with ThreadPoolExecutor(max_workers=1) as pool:
            projections = pool.submit(asyncio.run, _fetch(config, token_store)).result()
        plan = plan_skill_sync(home if home is not None else Path.home(), projections)
    except AuthenticationError as exc:
        raise _error(
            LocalErrorCode.SECRET_REVOKED,
            "The machine credential was rejected.",
            ComponentId.SECRET_STORE,
            retryable=False,
        ) from exc
    except StudioApiError as exc:
        _LOGGER.warning("skills.check: library unreachable (%s)", type(exc).__name__)
        raise _error(
            LocalErrorCode.INTERNAL_ERROR,
            "The Studio OS Library could not be reached.",
            ComponentId.DAEMON,
            retryable=True,
        ) from exc
    except SkillSyncError as exc:
        _LOGGER.warning("skills.check: invalid library skill (%s)", type(exc).__name__)
        raise _error(
            LocalErrorCode.INTERNAL_ERROR,
            "A Library skill could not be checked.",
            ComponentId.DAEMON,
            retryable=False,
        ) from exc
    return summarize(plan)
