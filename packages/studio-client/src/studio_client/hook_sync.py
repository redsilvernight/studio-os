"""Project effective Studio Library hooks into local harness configurations.

Same pipeline as :mod:`studio_client.skill_sync` (plan -> diff -> apply,
manifest, shared drift taxonomy, atomic writes, backups), with one extra
gate: a hook is executable code, so it is only installed once the user has
consented locally to the exact fingerprint of its canonical content.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from studio_contracts.library import HookContent, HookEvent, HookMode, HookOs, HookScript, HookShell

from studio_client.context.library import LibraryContextProvider
from studio_client.drift import SyncState, classify_state, hash_text
from studio_client.skill_sync import _STABLE_KEY_RE, _WINDOWS_RESERVED_NAMES, _atomic_write

HookStatus = Literal["installed", "needs_consent", "disabled", "no_variant"]
TargetState = SyncState | Literal["obsolete"]
TargetRole = Literal["script", "claude_settings", "opencode_plugin"]

_MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_RELATIVE = (".studio-os", "library-hooks-manifest.json")
_CONSENT_RELATIVE = (".studio", "hook-consent.json")
_DISABLED_RELATIVE = (".studio", "hook-disabled.json")
_CLAUDE_SETTINGS_RELATIVE = (".claude", "settings.json")
_CLAUDE_SCRIPTS_RELATIVE = (".claude", "studio-hooks")
_OPENCODE_PLUGIN_RELATIVE = (".config", "opencode", "plugin", "studio-hooks.js")

CLAUDE_EVENTS: dict[HookEvent, str] = {
    HookEvent.SESSION_START: "SessionStart",
    HookEvent.SESSION_END: "SessionEnd",
    HookEvent.USER_PROMPT: "UserPromptSubmit",
    HookEvent.PRE_TOOL: "PreToolUse",
    HookEvent.POST_TOOL: "PostToolUse",
    HookEvent.STOP: "Stop",
    HookEvent.SUBAGENT_STOP: "SubagentStop",
    HookEvent.NOTIFICATION: "Notification",
    HookEvent.PRE_COMPACT: "PreCompact",
}

OPENCODE_EVENTS: dict[HookEvent, str] = {
    HookEvent.PRE_TOOL: "tool.execute.before",
    HookEvent.POST_TOOL: "tool.execute.after",
    HookEvent.SESSION_START: "session.created",
    HookEvent.STOP: "session.idle",
}
_OPENCODE_BLOCKING_EVENTS = frozenset({HookEvent.PRE_TOOL})

_SHELL_EXTENSIONS: dict[HookShell, str] = {
    HookShell.PWSH: "ps1",
    HookShell.BASH: "sh",
    HookShell.SH: "sh",
    HookShell.PYTHON: "py",
    HookShell.NODE: "js",
}
_SHELL_ARGV: dict[HookShell, tuple[str, ...]] = {
    HookShell.PWSH: ("pwsh", "-NoProfile", "-File"),
    HookShell.BASH: ("bash",),
    HookShell.SH: ("sh",),
    HookShell.PYTHON: ("python",),
    HookShell.NODE: ("node",),
}
_SAFE_ARG_RE = re.compile(r"\A[A-Za-z0-9_./:-]+\Z")


class HookSyncError(RuntimeError):
    """Base error for invalid or unsafe hook synchronization."""


class HookSyncConflictError(HookSyncError):
    """Raised when a synchronization would overwrite local content."""


@dataclass(frozen=True)
class HookProjection:
    """One effective, active Library hook with its parsed content."""

    stable_key: str
    version: int
    version_origin: str
    scope: str
    title: str
    content: HookContent

    @property
    def fingerprint(self) -> str:
        return hook_fingerprint(self.content)


@dataclass(frozen=True)
class HookFileTarget:
    """Desired state of one file touched by the synchronization."""

    role: TargetRole
    path: Path
    state: TargetState
    current_text: str | None
    current_sha256: str | None
    desired_text: str | None


@dataclass(frozen=True)
class HookPlanEntry:
    """Per-hook decision and the harness projections it yields."""

    projection: HookProjection
    status: HookStatus
    claude_event: str
    script: HookScript | None
    script_path: Path | None
    command: str | None
    opencode_event: str | None
    reports: tuple[str, ...]


@dataclass(frozen=True)
class HookSyncPlan:
    """A deterministic, side-effect-free synchronization plan."""

    home: Path
    entries: tuple[HookPlanEntry, ...]
    removed: tuple[str, ...]
    files: tuple[HookFileTarget, ...]
    manifest_path: Path
    manifest_text: str
    state_files: tuple[tuple[Path, str | None, str], ...]

    @property
    def pending(self) -> tuple[HookFileTarget, ...]:
        return tuple(target for target in self.files if target.state != "current")

    @property
    def locally_modified(self) -> tuple[HookFileTarget, ...]:
        return tuple(target for target in self.files if target.state == "locally_modified")

    @property
    def needs_consent(self) -> tuple[HookPlanEntry, ...]:
        return tuple(entry for entry in self.entries if entry.status == "needs_consent")

    @property
    def is_current(self) -> bool:
        manifest_current = _read_text(self.manifest_path) == self.manifest_text
        states_current = all(current == desired for _, current, desired in self.state_files)
        return not self.pending and manifest_current and states_current


@dataclass(frozen=True)
class HookSyncResult:
    written: tuple[Path, ...]
    deleted: tuple[Path, ...]
    backups: tuple[Path, ...]
    manifest_path: Path


def hook_fingerprint(content: HookContent) -> str:
    """sha256 of the canonical JSON of a hook content (consent key)."""

    canonical = json.dumps(
        content.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hash_text(canonical)


async def fetch_hook_projections(
    api: Any,
    project_id: UUID | None,
    limit: int = 100,
) -> tuple[HookProjection, ...]:
    """Fetch effective active hooks; deprecated or draft rows are absent."""

    rows = await LibraryContextProvider(api).fetch_effective_versions(
        project_id, kind="hook", limit=limit
    )
    projections: list[HookProjection] = []
    for row in rows:
        if str(getattr(row.resource, "status", "active")) != "active":
            continue
        try:
            content = HookContent.model_validate(dict(row.version_row.content))
        except ValidationError as exc:
            raise HookSyncError(
                f"library hook/{row.resource.stable_key} v{row.version} "
                "violates studio.library.hook/v1"
            ) from exc
        projections.append(
            HookProjection(
                stable_key=row.resource.stable_key,
                version=row.version,
                version_origin=row.version_origin,
                scope=str(row.resource.scope),
                title=row.version_row.title,
                content=content,
            )
        )
    return tuple(sorted(projections, key=lambda item: item.stable_key))


def current_hook_os() -> HookOs:
    if sys.platform.startswith("win"):
        return HookOs.WINDOWS
    if sys.platform == "darwin":
        return HookOs.MACOS
    return HookOs.LINUX


def select_script(content: HookContent, os_name: HookOs) -> HookScript | None:
    """Exact OS variant first, then `any`; `None` when nothing fits."""

    for wanted in (os_name, HookOs.ANY):
        for script in content.scripts:
            if script.os == wanted:
                return script
    return None


def plan_hook_sync(
    home: Path | str,
    projections: Sequence[HookProjection],
    *,
    consent: Iterable[str] = (),
    disable: Iterable[str] = (),
    os_name: HookOs | None = None,
) -> HookSyncPlan:
    """Inspect hook targets and local consent without changing the filesystem."""

    root = Path(home).expanduser().resolve()
    target_os = os_name or current_hook_os()
    by_key: dict[str, HookProjection] = {}
    for projection in sorted(projections, key=lambda item: item.stable_key):
        _validate_projection(projection)
        if projection.stable_key in by_key:
            raise HookSyncError(f"duplicate hook stable_key: {projection.stable_key!r}")
        by_key[projection.stable_key] = projection

    consent_path = root.joinpath(*_CONSENT_RELATIVE)
    disabled_path = root.joinpath(*_DISABLED_RELATIVE)
    consents = _load_consents(consent_path)
    disabled = _load_disabled(disabled_path)
    for key in consent:
        if key not in by_key:
            raise HookSyncError(f"cannot consent to unknown or inactive hook: {key!r}")
        consents[key] = by_key[key].fingerprint
        disabled.discard(key)
    for key in disable:
        disabled.add(key)
        consents.pop(key, None)

    manifest_path = root.joinpath(*_MANIFEST_RELATIVE)
    manifest = _load_manifest(manifest_path)
    previous_rows = {row["stable_key"]: row for row in manifest["hooks"]}

    entries = [
        _plan_entry(root, projection, consents, disabled, target_os)
        for projection in by_key.values()
    ]
    installed = [entry for entry in entries if entry.status == "installed"]
    installed_keys = {entry.projection.stable_key for entry in installed}
    removed = tuple(sorted(key for key in previous_rows if key not in installed_keys))

    files: list[HookFileTarget] = []
    desired_scripts: set[Path] = set()
    for entry in installed:
        assert entry.script is not None and entry.script_path is not None
        previous = previous_rows.get(entry.projection.stable_key)
        desired_scripts.add(entry.script_path)
        managed_hash = (
            previous.get("sha256")
            if previous and _resolve_managed(root, previous.get("script")) == entry.script_path
            else None
        )
        files.append(
            _plan_file(
                "script",
                entry.script_path,
                _render_script(entry.script),
                managed_hash if isinstance(managed_hash, str) else None,
            )
        )
    for row in previous_rows.values():
        old_path = _resolve_managed(root, row.get("script"))
        if old_path is not None and old_path not in desired_scripts and old_path.is_file():
            files.append(_plan_deletion("script", old_path))

    managed_commands = {
        str(row["command"]) for row in previous_rows.values() if isinstance(row.get("command"), str)
    } | {entry.command for entry in installed if entry.command}
    settings_target = _plan_claude_settings(root, installed, managed_commands)
    if settings_target is not None:
        files.append(settings_target)

    plugin_path = root.joinpath(*_OPENCODE_PLUGIN_RELATIVE)
    opencode_entries = [entry for entry in installed if entry.opencode_event is not None]
    plugin_hash = manifest.get("opencode_plugin_sha256")
    plugin_text: str | None = None
    if opencode_entries:
        plugin_text = render_opencode_plugin(opencode_entries)
        files.append(
            _plan_file(
                "opencode_plugin",
                plugin_path,
                plugin_text,
                plugin_hash if isinstance(plugin_hash, str) else None,
            )
        )
    elif isinstance(plugin_hash, str) and plugin_path.is_file():
        files.append(_plan_deletion("opencode_plugin", plugin_path))

    manifest_text = _render_manifest(root, installed, plugin_text)
    state_files = (
        (consent_path, _read_text(consent_path), _render_json(dict(sorted(consents.items())))),
        (disabled_path, _read_text(disabled_path), _render_json(sorted(disabled))),
    )
    return HookSyncPlan(
        home=root,
        entries=tuple(entries),
        removed=removed,
        files=tuple(files),
        manifest_path=manifest_path,
        manifest_text=manifest_text,
        state_files=tuple(
            (path, current, desired)
            for path, current, desired in state_files
            if current is not None or desired.strip() not in {"{}", "[]"}
        ),
    )


def diff_hook_plan(plan: HookSyncPlan) -> str:
    """Deterministic unified diffs of every file the plan would change."""

    chunks: list[str] = []
    for target in plan.files:
        if target.state == "current":
            continue
        relative = target.path.relative_to(plan.home).as_posix()
        current_lines = (
            [] if target.current_text is None else target.current_text.splitlines(keepends=True)
        )
        desired_lines = (
            [] if target.desired_text is None else target.desired_text.splitlines(keepends=True)
        )
        chunks.extend(
            difflib.unified_diff(
                current_lines,
                desired_lines,
                fromfile="/dev/null" if target.state == "missing" else relative,
                tofile="/dev/null" if target.state == "obsolete" else relative,
                lineterm="\n",
            )
        )
    return "".join(chunks)


def apply_hook_sync(plan: HookSyncPlan, *, overwrite: bool = False) -> HookSyncResult:
    """Apply a plan: back up, write atomically, delete obsolete, persist state."""

    conflicts = plan.locally_modified
    if conflicts and not overwrite:
        paths = ", ".join(str(target.path) for target in conflicts)
        raise HookSyncConflictError(
            f"refusing to overwrite locally modified hook files without overwrite=True: {paths}"
        )
    _verify_plan_is_fresh(plan)

    backups: list[Path] = []
    backup_root = (
        plan.home
        / ".studio-os"
        / "backups"
        / "hooks"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    for target in plan.pending:
        needs_backup = target.current_text is not None and (
            target.role == "claude_settings" or target.state in {"locally_modified", "obsolete"}
        )
        if needs_backup:
            assert target.current_text is not None
            backup_path = backup_root / target.path.relative_to(plan.home)
            _atomic_write(backup_path, target.current_text)
            backups.append(backup_path)

    written: list[Path] = []
    deleted: list[Path] = []
    for target in plan.pending:
        if target.desired_text is None:
            target.path.unlink()
            deleted.append(target.path)
        else:
            _atomic_write(target.path, target.desired_text)
            written.append(target.path)
    _atomic_write(plan.manifest_path, plan.manifest_text)
    for path, current, desired in plan.state_files:
        if current != desired:
            _atomic_write(path, desired)
    return HookSyncResult(
        written=tuple(written),
        deleted=tuple(deleted),
        backups=tuple(backups),
        manifest_path=plan.manifest_path,
    )


def render_opencode_plugin(entries: Sequence[HookPlanEntry]) -> str:
    """Generated OpenCode plugin dispatching hook events to local scripts."""

    hooks = [
        {
            "argv": [*_SHELL_ARGV[entry.script.shell], entry.script_path.as_posix()],
            "blocking": entry.projection.content.mode is HookMode.BLOCKING,
            "event": entry.opencode_event,
            "matcher": entry.projection.content.matcher,
            "stable_key": entry.projection.stable_key,
            "timeout_ms": entry.projection.content.timeout_seconds * 1000,
        }
        for entry in sorted(entries, key=lambda item: item.projection.stable_key)
        if entry.script is not None and entry.script_path is not None
    ]
    payload = json.dumps(hooks, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "// Generated by `studio-client hooks-library sync`. Do not edit: changes are\n"
        "// detected as local drift and never silently overwritten.\n"
        'import { spawnSync } from "node:child_process";\n'
        "\n"
        f"const HOOKS = {payload};\n"
        "\n"
        "function run(hook, payload) {\n"
        "  const result = spawnSync(hook.argv[0], hook.argv.slice(1), {\n"
        "    input: JSON.stringify(payload ?? {}),\n"
        '    encoding: "utf-8",\n'
        "    timeout: hook.timeout_ms,\n"
        "  });\n"
        "  if (hook.blocking && (result.error || result.status !== 0)) {\n"
        "    throw new Error(\n"
        '      `studio hook ${hook.stable_key} blocked: ${(result.stderr || "").trim()}`,\n'
        "    );\n"
        "  }\n"
        "}\n"
        "\n"
        "function matches(hook, tool) {\n"
        '  return !hook.matcher || new RegExp(`^(?:${hook.matcher})$`).test(tool ?? "");\n'
        "}\n"
        "\n"
        "export const StudioHooks = async () => ({\n"
        '  "tool.execute.before": async (input, output) => {\n'
        "    for (const hook of HOOKS) {\n"
        '      if (hook.event === "tool.execute.before" && matches(hook, input.tool)) {\n'
        "        run(hook, { input, args: output.args });\n"
        "      }\n"
        "    }\n"
        "  },\n"
        '  "tool.execute.after": async (input, output) => {\n'
        "    for (const hook of HOOKS) {\n"
        '      if (hook.event === "tool.execute.after" && matches(hook, input.tool)) {\n'
        "        run(hook, { input, output });\n"
        "      }\n"
        "    }\n"
        "  },\n"
        "  event: async ({ event }) => {\n"
        "    for (const hook of HOOKS) {\n"
        "      if (hook.event === event.type) run(hook, { event });\n"
        "    }\n"
        "  },\n"
        "});\n"
    )


def _plan_entry(
    root: Path,
    projection: HookProjection,
    consents: dict[str, str],
    disabled: set[str],
    target_os: HookOs,
) -> HookPlanEntry:
    content = projection.content
    claude_event = CLAUDE_EVENTS[content.event]
    reports: list[str] = ["codex:not_supported"]
    opencode_event = OPENCODE_EVENTS.get(content.event)
    if opencode_event is None:
        reports.append(f"opencode:event_not_expressible:{content.event.value}")
    elif content.mode is HookMode.BLOCKING and content.event not in _OPENCODE_BLOCKING_EVENTS:
        reports.append(f"opencode:blocking_not_expressible:{content.event.value}")
        opencode_event = None
    script = select_script(content, target_os)
    status: HookStatus
    if projection.stable_key in disabled:
        status = "disabled"
    elif consents.get(projection.stable_key) != projection.fingerprint:
        status = "needs_consent"
    elif script is None:
        status = "no_variant"
        reports.append(f"no_variant:{target_os.value}")
    else:
        status = "installed"
    if status != "installed" or script is None:
        return HookPlanEntry(
            projection, status, claude_event, None, None, None, None, tuple(reports)
        )
    script_path = root.joinpath(
        *_CLAUDE_SCRIPTS_RELATIVE,
        f"{projection.stable_key}.{_SHELL_EXTENSIONS[script.shell]}",
    )
    return HookPlanEntry(
        projection=projection,
        status=status,
        claude_event=claude_event,
        script=script,
        script_path=script_path,
        command=_command(script.shell, script_path),
        opencode_event=opencode_event,
        reports=tuple(reports),
    )


def _command(shell: HookShell, script_path: Path) -> str:
    parts = [*_SHELL_ARGV[shell], script_path.as_posix()]
    return " ".join(part if _SAFE_ARG_RE.fullmatch(part) else f'"{part}"' for part in parts)


def _render_script(script: HookScript) -> str:
    body = script.body.replace("\r\n", "\n").replace("\r", "\n")
    return body if body.endswith("\n") else f"{body}\n"


def _claude_group(entry: HookPlanEntry) -> dict[str, Any]:
    group: dict[str, Any] = {}
    if entry.projection.content.matcher is not None:
        group["matcher"] = entry.projection.content.matcher
    group["hooks"] = [
        {
            "type": "command",
            "command": entry.command,
            "timeout": entry.projection.content.timeout_seconds,
        }
    ]
    return group


def merge_claude_hooks(
    settings: dict[str, Any],
    desired: dict[str, list[dict[str, Any]]],
    managed_commands: set[str],
) -> dict[str, Any]:
    """Replace managed hook groups in a Claude Code settings mapping.

    A hook is managed only if its command is traced in the manifest (or is
    about to be); every other entry is preserved verbatim and in place."""

    merged = copy.deepcopy(settings)
    hooks = merged.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise HookSyncError("Claude settings `hooks` is not an object; refusing to merge")
    result: dict[str, Any] = {}
    for event in [*hooks.keys(), *(name for name in sorted(desired) if name not in hooks)]:
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise HookSyncError(f"Claude settings hooks.{event} is not a list; refusing to merge")
        unmanaged: list[Any] = []
        managed_present: list[Any] = []
        stripped = False
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list):
                unmanaged.append(group)
                continue
            keep = [
                hook
                for hook in inner
                if not (isinstance(hook, dict) and hook.get("command") in managed_commands)
            ]
            if len(keep) == len(inner):
                unmanaged.append(group)
            elif keep:
                unmanaged.append({**group, "hooks": keep})
                stripped = True
            else:
                managed_present.append(group)
        wanted = desired.get(event, [])
        if not stripped and managed_present == wanted:
            if groups or event in hooks:
                result[event] = groups
            continue
        combined = unmanaged + wanted
        if combined:
            result[event] = combined
    if result or "hooks" in merged:
        merged["hooks"] = result
    return merged


def _plan_claude_settings(
    root: Path,
    installed: Sequence[HookPlanEntry],
    managed_commands: set[str],
) -> HookFileTarget | None:
    path = root.joinpath(*_CLAUDE_SETTINGS_RELATIVE)
    current_text = _read_text(path)
    if current_text is None:
        settings: dict[str, Any] = {}
    else:
        try:
            parsed = json.loads(current_text)
        except json.JSONDecodeError as exc:
            raise HookSyncError(f"Claude settings is not valid JSON: {path}") from exc
        if not isinstance(parsed, dict):
            raise HookSyncError(f"Claude settings is not a JSON object: {path}")
        settings = parsed
    desired: dict[str, list[dict[str, Any]]] = {}
    for entry in sorted(installed, key=lambda item: item.projection.stable_key):
        desired.setdefault(entry.claude_event, []).append(_claude_group(entry))
    merged = merge_claude_hooks(settings, desired, managed_commands)
    if merged == settings:
        if current_text is None:
            return None
        return HookFileTarget(
            "claude_settings", path, "current", current_text, hash_text(current_text), current_text
        )
    desired_text = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    state: TargetState = "missing" if current_text is None else "outdated"
    return HookFileTarget(
        "claude_settings",
        path,
        state,
        current_text,
        None if current_text is None else hash_text(current_text),
        desired_text,
    )


def _plan_file(
    role: TargetRole,
    path: Path,
    desired: str,
    managed_hash: str | None,
) -> HookFileTarget:
    if path.exists() and not path.is_file():
        raise HookSyncError(f"hook target is not a regular file: {path}")
    current = _read_text(path)
    state = classify_state(current, desired, managed_hash)
    return HookFileTarget(
        role, path, state, current, None if current is None else hash_text(current), desired
    )


def _plan_deletion(role: TargetRole, path: Path) -> HookFileTarget:
    current = _read_text(path)
    return HookFileTarget(
        role, path, "obsolete", current, None if current is None else hash_text(current), None
    )


def _render_manifest(
    root: Path,
    installed: Sequence[HookPlanEntry],
    plugin_text: str | None,
) -> str:
    rows = []
    for entry in sorted(installed, key=lambda item: item.projection.stable_key):
        assert entry.script is not None and entry.script_path is not None
        rows.append(
            {
                "claude_event": entry.claude_event,
                "command": entry.command,
                "fingerprint": entry.projection.fingerprint,
                "opencode_event": entry.opencode_event,
                "scope": entry.projection.scope,
                "script": entry.script_path.relative_to(root).as_posix(),
                "sha256": hash_text(_render_script(entry.script)),
                "stable_key": entry.projection.stable_key,
                "version": entry.projection.version,
                "version_origin": entry.projection.version_origin,
            }
        )
    return _render_json(
        {
            "hooks": rows,
            "opencode_plugin_sha256": None if plugin_text is None else hash_text(plugin_text),
            "schema_version": _MANIFEST_SCHEMA_VERSION,
        }
    )


def _load_manifest(path: Path) -> dict[str, Any]:
    empty: dict[str, Any] = {"hooks": [], "opencode_plugin_sha256": None}
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        return empty
    rows = payload.get("hooks")
    if not isinstance(rows, list):
        return empty
    return {
        "hooks": [
            row for row in rows if isinstance(row, dict) and isinstance(row.get("stable_key"), str)
        ],
        "opencode_plugin_sha256": payload.get("opencode_plugin_sha256"),
    }


def _load_consents(path: Path) -> dict[str, str]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _load_disabled(path: Path) -> set[str]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        return set()
    return {key for key in payload if isinstance(key, str)}


def _load_json(path: Path) -> Any:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _resolve_managed(root: Path, relative: object) -> Path | None:
    """Manifest script paths are only trusted inside the managed scripts dir."""

    if not isinstance(relative, str):
        return None
    scripts_dir = root.joinpath(*_CLAUDE_SCRIPTS_RELATIVE)
    candidate = (root / relative).resolve()
    if candidate.parent != scripts_dir:
        return None
    return candidate


def _validate_projection(projection: HookProjection) -> None:
    key = projection.stable_key
    if (
        not _STABLE_KEY_RE.fullmatch(key)
        or ".." in key
        or key.endswith(".")
        or key.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
    ):
        raise HookSyncError(f"unsafe hook stable_key: {key!r}")
    if projection.version <= 0:
        raise HookSyncError(f"invalid hook version for {key!r}: {projection.version}")


def _verify_plan_is_fresh(plan: HookSyncPlan) -> None:
    for target in plan.files:
        current = _read_text(target.path)
        current_hash = None if current is None else hash_text(current)
        if current_hash != target.current_sha256:
            raise HookSyncConflictError(f"hook target changed since planning: {target.path}")


def _read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HookSyncError(f"hook target is not valid UTF-8: {path}") from exc


def _render_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
