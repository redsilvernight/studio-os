"""Workstation setup engine behind the Desktop « Configurer ce poste » action.

No second engine: the managed files come from ``hooks`` / ``opencode_plugin``
(the same templates ``setup-hooks`` writes), the skills from ``skill_sync`` and
the adapter drift gate from ``adapters_check``. This module only adds the
guard rails the CLI flag ``--overwrite`` lacks:

* planning is side-effect free and compares *content*, not just the marker, so a
  hand-edited copy that still carries the managed marker is reported as
  ``differs`` instead of being silently regenerated;
* a file that differs from the managed render is replaced only when the caller
  names it explicitly, after a backup under ``~/.studio-os/backups/setup``;
* every write is read back: an item is reported ``written`` only when the file
  on disk equals the render.

Nothing here reads or returns a secret; the templates carry none.
"""

from __future__ import annotations

import difflib
import hashlib
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from studio_contracts.local.common import contains_absolute_path, contains_secret_material

from studio_client.harness.redaction import redact_text
from studio_client.hooks import (
    GUARD_REL,
    HARNESSES,
    HarnessSpec,
    detect_harnesses,
    is_managed,
    render_guard,
    render_hook,
)
from studio_client.opencode_plugin import plugin_target, render_plugin
from studio_client.skill_sync import (
    SkillSyncPlan,
    SkillSyncResult,
    SkillTargetPlan,
    apply_skill_sync,
)

ItemKind = Literal["hook", "guard", "plugin"]
ItemState = Literal["missing", "current", "differs"]
ItemOutcome = Literal["written", "unchanged", "skipped", "failed"]

DIFF_MAX_LINES = 80
DIFF_MAX_CHARS = 8000
GUARD_ITEM_ID = "guard"
PLUGIN_ITEM_ID = "plugin"
# Harness whose hook file is wired by the harness' own settings, which the
# setup never edits (DEC-0096): the file is deployed, the registration stays manual.
_MANUAL_REGISTRATION = frozenset({"claude-code", "codex"})


@dataclass(frozen=True)
class SetupItem:
    """One managed file the setup would write, with its comparison to disk."""

    item_id: str
    kind: ItemKind
    harness: str
    target: Path
    rendered: str
    state: ItemState
    managed: bool
    lines_added: int
    lines_removed: int
    diff: str
    diff_truncated: bool
    needs_registration: bool

    @property
    def action(self) -> Literal["deploy", "none", "overwrite"]:
        if self.state == "missing":
            return "deploy"
        return "none" if self.state == "current" else "overwrite"


@dataclass(frozen=True)
class SetupHooksPlan:
    home: Path
    detected: tuple[HarnessSpec, ...]
    items: tuple[SetupItem, ...]

    @property
    def pending(self) -> tuple[SetupItem, ...]:
        return tuple(item for item in self.items if item.state != "current")


@dataclass(frozen=True)
class ItemResult:
    item_id: str
    outcome: ItemOutcome
    backed_up: bool = False


@dataclass(frozen=True)
class SetupHooksResult:
    items: tuple[ItemResult, ...]
    backup_root: Path | None


def detected_harnesses(home: Path, path_dirs: Sequence[str]) -> tuple[HarnessSpec, ...]:
    """Harnesses installed under ``home`` (same detection as ``setup-hooks``)."""
    return tuple(detect_harnesses(home, tuple(path_dirs)))


def _read(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Unreadable or not UTF-8: certainly not our render, never silently replaced.
        return ""


def _masked(line: str) -> str:
    """The contract refuses credential-shaped values and absolute paths: such a
    line is hidden rather than letting a foreign file break the whole preview."""
    if contains_secret_material(line) or contains_absolute_path(line):
        return f"{line[:1]}[ligne masquée]"
    return line


def _bounded_diff(label: str, current: str, rendered: str) -> tuple[str, int, int, bool]:
    """Redacted, bounded unified diff (current → managed render). Paths are
    replaced by a neutral label: the contract carries no filesystem path."""
    lines = list(
        difflib.unified_diff(
            current.splitlines(),
            rendered.splitlines(),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
            lineterm="",
        )
    )
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    truncated = len(lines) > DIFF_MAX_LINES
    text = redact_text("\n".join(_masked(line) for line in lines[:DIFF_MAX_LINES]))
    if len(text) > DIFF_MAX_CHARS:
        text, truncated = text[:DIFF_MAX_CHARS], True
    if contains_secret_material(text) or contains_absolute_path(text):
        # A pattern that spans lines: hide the whole diff rather than risk a leak.
        text, truncated = "[diff masqué]", True
    return text, added, removed, truncated


def _item(
    item_id: str,
    kind: ItemKind,
    harness: str,
    target: Path,
    rendered: str,
    managed_check: bool,
    needs_registration: bool,
) -> SetupItem:
    current = _read(target)
    if current is None:
        state: ItemState = "missing"
        diff, added, removed, truncated = "", 0, 0, False
    elif current == rendered:
        state, diff, added, removed, truncated = "current", "", 0, 0, False
    else:
        state = "differs"
        diff, added, removed, truncated = _bounded_diff(item_id, current, rendered)
    return SetupItem(
        item_id=item_id,
        kind=kind,
        harness=harness,
        target=target,
        rendered=rendered,
        state=state,
        managed=managed_check,
        lines_added=added,
        lines_removed=removed,
        diff=diff,
        diff_truncated=truncated,
        needs_registration=needs_registration,
    )


def plan_hooks(home: Path, specs: Iterable[HarnessSpec]) -> SetupHooksPlan:
    """Dry-run of ``setup-hooks``: hook + guard + plugin for the given harnesses."""
    detected = tuple(specs)
    items: list[SetupItem] = []
    for spec in detected:
        target = home / spec.hook_rel
        items.append(
            _item(
                f"hook:{spec.harness}",
                "hook",
                spec.harness,
                target,
                render_hook(spec),
                is_managed(target),
                spec.harness in _MANUAL_REGISTRATION,
            )
        )
    names = {spec.harness for spec in detected}
    if names & {"claude-code", "opencode"}:
        target = home / GUARD_REL
        items.append(
            _item(
                GUARD_ITEM_ID,
                "guard",
                "git-guard",
                target,
                render_guard(),
                is_managed(target),
                False,
            )
        )
    if "opencode" in names:
        target = plugin_target(home)
        items.append(
            _item(
                PLUGIN_ITEM_ID,
                "plugin",
                "opencode-plugin",
                target,
                render_plugin(home),
                is_managed(target),
                False,
            )
        )
    return SetupHooksPlan(home=home, detected=detected, items=tuple(items))


def plan_fingerprint(plan: SetupHooksPlan) -> str:
    """Stable digest of what the plan would do: a confirmation is bound to it, so
    a file edited after the preview invalidates the confirmation."""
    digest = hashlib.sha256()
    for item in plan.items:
        current = _read(item.target)
        digest.update(
            f"{item.item_id}|{item.state}|{hashlib.sha256((current or '').encode()).hexdigest()}|"
            f"{hashlib.sha256(item.rendered.encode()).hexdigest()}\n".encode()
        )
    return digest.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def apply_hooks(
    plan: SetupHooksPlan,
    *,
    overwrite: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> SetupHooksResult:
    """Write the missing files; replace a differing file only when named in
    ``overwrite``, backing it up first. Re-plans from disk right before each
    write: a file that changed since the preview is skipped, never clobbered."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_root = plan.home / ".studio-os" / "backups" / "setup" / stamp
    results: list[ItemResult] = []
    used_backup = False
    for item in plan.items:
        live = _read(item.target)
        if live == item.rendered:
            results.append(ItemResult(item.item_id, "unchanged"))
            continue
        fresh_state: ItemState = "missing" if live is None else "differs"
        if fresh_state != item.state:
            # Changed between preview and apply: the confirmation no longer fits.
            results.append(ItemResult(item.item_id, "skipped"))
            continue
        backed_up = False
        if fresh_state == "differs":
            if item.item_id not in overwrite:
                results.append(ItemResult(item.item_id, "skipped"))
                continue
            try:
                _atomic_write(backup_root / f"{item.item_id.replace(':', '_')}.bak", live or "")
            except OSError:
                results.append(ItemResult(item.item_id, "failed"))
                continue
            backed_up = used_backup = True
        try:
            _atomic_write(item.target, item.rendered)
        except OSError:
            results.append(ItemResult(item.item_id, "failed", backed_up))
            continue
        confirmed = _read(item.target) == item.rendered
        results.append(ItemResult(item.item_id, "written" if confirmed else "failed", backed_up))
    return SetupHooksResult(items=tuple(results), backup_root=backup_root if used_backup else None)


def skills_without_conflicts(plan: SkillSyncPlan) -> SkillSyncPlan:
    """A copy of ``plan`` that leaves every locally modified target alone: it is
    never overwritten from the Desktop, only reported."""
    entries = tuple(
        replace(
            entry,
            targets=(
                _keep(entry.targets[0]),
                _keep(entry.targets[1]),
            ),
        )
        for entry in plan.entries
    )
    return replace(plan, entries=entries)


def _keep(target: SkillTargetPlan) -> SkillTargetPlan:
    return replace(target, state="current") if target.state == "locally_modified" else target


def skills_pending(plan: SkillSyncPlan) -> int:
    """Targets a conflict-free apply would write (missing or outdated)."""
    return len(plan.missing) + len(plan.outdated)


def apply_skills(plan: SkillSyncPlan) -> SkillSyncResult | None:
    """Sync missing/outdated skills; ``None`` when there is nothing to write, so a
    second run performs zero writes (``apply_skill_sync`` always rewrites the manifest)."""
    safe = skills_without_conflicts(plan)
    if skills_pending(safe) == 0:
        return None
    return apply_skill_sync(safe)


__all__ = [
    "GUARD_ITEM_ID",
    "HARNESSES",
    "PLUGIN_ITEM_ID",
    "ItemResult",
    "SetupHooksPlan",
    "SetupHooksResult",
    "SetupItem",
    "apply_hooks",
    "apply_skills",
    "detected_harnesses",
    "plan_fingerprint",
    "plan_hooks",
    "skills_pending",
    "skills_without_conflicts",
]
