"""Read-only ``setup-hooks.check`` bridge command.

Reuses ``hooks.detect_harnesses``, ``hooks.is_managed``, ``hooks.render_hook``,
``hooks.render_guard``, ``opencode_plugin.render_plugin`` and
``opencode_plugin.guard_state`` (the same engine as
``studio-client setup-hooks --dry-run``) and never writes: the Desktop only
learns which hooks/guard/plugin are managed, missing, foreign or up-to-date for
each detected harness. No hook content or filesystem path leaves this module.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.machine_setup import (
    HookCheckEntry,
    HookCheckState,
    SetupHooksCheckRequest,
    SetupHooksCheckResult,
)

from studio_client.config import ClientConfig
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.hooks import HARNESSES, detect_harnesses, guard_state, is_managed, render_guard, render_hook
from studio_client.opencode_plugin import plugin_target, render_plugin
from studio_client.tokens import TokenStore, origin_of

_LOGGER = logging.getLogger("studio_client.daemon.hooks_check")


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _hook_check_state(home: Path, spec, target: Path) -> HookCheckState:
    current = _read(target)
    if current is None:
        return HookCheckState.MISSING
    rendered = render_hook(spec)
    if current == rendered:
        return HookCheckState.MANAGED
    if is_managed(target):
        return HookCheckState.FOREIGN
    return HookCheckState.FOREIGN


def _guard_check_state(home: Path) -> HookCheckState:
    target = home / ".claude" / "scripts" / "studio-git-guard.ps1"
    current = _read(target)
    if current is None:
        return HookCheckState.MISSING
    rendered = render_guard()
    if current == rendered:
        return HookCheckState.MANAGED
    if is_managed(target):
        return HookCheckState.FOREIGN
    return HookCheckState.FOREIGN


def _plugin_check_state(home: Path) -> HookCheckState:
    target = plugin_target(home)
    current = _read(target)
    if current is None:
        return HookCheckState.MISSING
    rendered = render_plugin(home)
    if current == rendered:
        return HookCheckState.MANAGED
    if is_managed(target):
        return HookCheckState.FOREIGN
    return HookCheckState.FOREIGN


def check_hooks(
    config: ClientConfig,
    token_store: TokenStore,
    *,
    home: Path | None = None,
    path_dirs: Callable[[], tuple[str, ...]] | None = None,
) -> SetupHooksCheckResult:
    """Compare the effective managed hooks/guard/plugin with the local harness copies."""
    _ = config, token_store
    actual_home = home if home is not None else Path.home()
    actual_path_dirs = path_dirs if path_dirs is not None else (lambda: ())

    detected = detect_harnesses(actual_home, actual_path_dirs())
    entries: list[HookCheckEntry] = []
    for spec in detected:
        hook_target = actual_home / spec.hook_rel
        hook_state = _hook_check_state(actual_home, spec, hook_target)

        guard_state_entry: HookCheckState | None = None
        if spec.harness in {"claude-code", "opencode"}:
            guard_state_entry = _guard_check_state(actual_home)

        plugin_state_entry: HookCheckState | None = None
        if spec.harness == "opencode":
            plugin_state_entry = _plugin_check_state(actual_home)

        entries.append(
            HookCheckEntry(
                harness=spec.harness,
                label=spec.label,
                hook_state=hook_state,
                guard_state=guard_state_entry,
                plugin_state=plugin_state_entry,
            )
        )

    return SetupHooksCheckResult(
        hooks=entries,
        checked_at=datetime.now(UTC),
    )