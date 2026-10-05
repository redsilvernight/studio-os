"""Read-only ``hooks.check`` bridge command.

Reuses ``hooks.detect_harnesses``, ``hooks.is_managed``, ``hooks.render_hook``,
``hooks.render_guard``, ``opencode_plugin.render_plugin`` and
(the same engine as
``studio-client setup-hooks --dry-run``) and never writes: the Desktop only
learns which hooks/guard/plugin are managed, missing, foreign or up-to-date for
each detected harness. No hook content or filesystem path leaves this module.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from studio_contracts.local.machine_setup import (
    HookCheckEntry,
    HookCheckState,
    SetupHooksCheckResult,
)

from studio_client.config import ClientConfig
from studio_client.hooks import detect_harnesses, render_guard, render_hook
from studio_client.opencode_plugin import plugin_target, render_plugin
from studio_client.tokens import TokenStore


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _state(target: Path, rendered: str) -> HookCheckState:
    current = _read(target)
    if current is None:
        return HookCheckState.MISSING
    return HookCheckState.MANAGED if current == rendered else HookCheckState.FOREIGN


def _guard_check_state(home: Path) -> HookCheckState:
    return _state(home / ".claude" / "scripts" / "studio-git-guard.ps1", render_guard())


def _plugin_check_state(home: Path) -> HookCheckState:
    return _state(plugin_target(home), render_plugin(home))


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
        hook_state = _state(hook_target, render_hook(spec))

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
