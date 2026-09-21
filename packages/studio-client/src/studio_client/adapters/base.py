from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from studio_contracts.resolution import ResolvedAgentDefinition

MANAGED_MARKER = "studio-managed"


class AdapterErrorCode(StrEnum):
    """Closed vocabulary of local adapter failures (P10/DEC-0074).

    These codes live in Bloc B only: they never cross the HTTP/MCP
    boundary and never appear in `studio_contracts`."""

    INVALID_CANONICAL = "invalid_canonical"
    HARNESS_MISMATCH = "harness_mismatch"
    UNSUPPORTED = "unsupported"
    MATERIALIZATION_FAILED = "materialization_failed"


class AdapterError(Exception):
    """Structured local translation/materialization failure.

    Either a complete `AdapterResult` is returned (success) or this is
    raised — never a silently half-built result."""

    def __init__(
        self,
        code: AdapterErrorCode,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


@dataclass(frozen=True)
class AdapterWarning:
    """A lossless-or-safe degradation note attached to a successful result.

    The translation stayed within its defined mapping, but the target
    harness cannot represent something (or the canonical input left
    something open) — so the caller sees it explicitly instead of
    discovering a silent omission."""

    code: str
    detail: str


@dataclass(frozen=True)
class AdapterArtifact:
    """One in-memory harness file produced by translation.

    `path` is a POSIX relative path anchored at the adapter's managed
    directory (e.g. `.claude/agents/<key>.md`). Translation never
    touches the filesystem — `materialize` does, after validation."""

    path: str
    content: str
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", sha256(self.content.encode("utf-8")).hexdigest())


@dataclass(frozen=True)
class AdapterResult:
    """Complete translation outcome: artifacts, warnings and
    non-normative metadata (adapter id, canonical identity echoes).
    The canonical input meaning is never altered to build this."""

    adapter_id: str
    artifacts: tuple[AdapterArtifact, ...]
    warnings: tuple[AdapterWarning, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


class CapabilitySupport(StrEnum):
    """How one harness represents one canonical need (P3.5).

    SUPPORTED: projected losslessly. DEGRADED: projected with an explicit
    warning note (never a silent drop). UNSUPPORTED: the adapter refuses
    with `AdapterError(UNSUPPORTED)` when the canonical definition actually
    needs it — fail explicit, never pretend.
    """

    SUPPORTED = "supported"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"


CAPABILITY_DIMENSIONS = (
    "rules",
    "skills",
    "subagents",
    "mcp",
    "permissions",
    "model_selection",
    "shell_execution",
)
"""Closed capability vocabulary every adapter reports on (P3.5)."""


class Adapter(Protocol):
    """Minimal local translation contract (P10).

    Pure translation only: no resolution, no runtime selection, no
    network, no subprocess, no prompt execution. Adapters read the
    canonical input and return a complete `AdapterResult` — or raise
    `AdapterError`. They never mutate the input."""

    @property
    def adapter_id(self) -> str: ...

    @property
    def managed_dir(self) -> str: ...

    def capabilities(self) -> dict[str, CapabilitySupport]:
        """This harness's support per `CAPABILITY_DIMENSIONS` (P3.5)."""
        ...

    def translate(
        self,
        resolved: ResolvedAgentDefinition,
        *,
        context: Any | None = None,
    ) -> AdapterResult: ...


_REGISTRY: dict[str, Adapter] = {}


def register_adapter(adapter: Adapter) -> None:
    """Adds (or replaces) one local adapter under its open-string id.

    A third harness needs only this call — never a core migration."""
    _REGISTRY[adapter.adapter_id] = adapter


def get_adapter(adapter_id: str) -> Adapter:
    """Local dispatch: open string id to adapter implementation.

    This dispatch lives in Bloc B only — never in `studio_contracts`,
    the resolver, the Registry, the Library or the generic composer."""
    try:
        return _REGISTRY[adapter_id]
    except KeyError:
        raise AdapterError(
            AdapterErrorCode.UNSUPPORTED,
            f"unknown adapter {adapter_id!r}",
            {"adapter_id": adapter_id, "known": sorted(_REGISTRY)},
        ) from None


def list_adapters() -> list[str]:
    """Sorted ids of the locally registered adapters."""
    return sorted(_REGISTRY)


def check_harness_compatible(adapter_id: str, resolved: ResolvedAgentDefinition) -> None:
    """Fails closed when the resolved runtime names another harness.

    A `None`/absent `harness_ref` means "no harness claim" and always
    translates. The runtime is never switched silently."""
    target = resolved.runtime.target if resolved.runtime is not None else None
    harness_ref = target.harness_ref if target is not None else None
    if harness_ref is not None and harness_ref != adapter_id:
        raise AdapterError(
            AdapterErrorCode.HARNESS_MISMATCH,
            f"resolved harness {harness_ref!r} does not match adapter {adapter_id!r}",
            {"adapter_id": adapter_id, "harness_ref": harness_ref},
        )


_SHELL_DEGRADED_NOTES = {
    "opencode": (
        "shell is bash-only and cannot be technically restricted — prefer reporting "
        "the exact command for the orchestrator over executing environment-mutating "
        "steps, and keep shell use minimal"
    ),
    "codex": (
        "the codex agent format carries no shell declaration — harness defaults "
        "apply, keep shell use minimal and non-destructive"
    ),
}
_DEFAULT_SHELL_DEGRADED_NOTE = (
    "shell execution is degraded on this harness — keep shell use minimal "
    "and non-destructive"
)


def capability_notes(
    adapter_id: str,
    capabilities: dict[str, CapabilitySupport],
    *,
    edit_policy: str | None,
) -> list[AdapterWarning]:
    """Standard degraded-capability notes (P3.5): one fixed text per
    dimension, driven by the adapter's own report — adapters add no
    per-agent prose here."""
    notes: list[AdapterWarning] = []
    if capabilities.get("shell_execution") == CapabilitySupport.DEGRADED:
        notes.append(
            AdapterWarning(
                "capability_degraded_shell",
                f"{adapter_id}: "
                + _SHELL_DEGRADED_NOTES.get(adapter_id, _DEFAULT_SHELL_DEGRADED_NOTE),
            )
        )
    if edit_policy == "deny" and capabilities.get("permissions") == CapabilitySupport.DEGRADED:
        notes.append(
            AdapterWarning(
                "capability_degraded_permissions",
                f"{adapter_id}: read-only policy enforced by instruction and harness "
                "default-deny, not by a technical allowlist — do not work around it",
            )
        )
    return notes


def ensure_supported(
    adapter_id: str,
    capabilities: dict[str, CapabilitySupport],
    *,
    edit_policy: str | None,
) -> None:
    """Fail explicit (P3.5): a canonical read-only demand on a harness that
    cannot represent permissions at all is an error, never a silent drop."""
    if edit_policy == "deny" and capabilities.get("permissions") == CapabilitySupport.UNSUPPORTED:
        raise AdapterError(
            AdapterErrorCode.UNSUPPORTED,
            f"{adapter_id} cannot represent the canonical read-only policy",
            {"adapter_id": adapter_id, "edit_policy": edit_policy},
        )


_WINDOWS_RESERVED_STEMS = (
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
"""Device names Windows refuses as path components (P10 §54 hardening)."""


def sanitize_agent_filename(stable_key: str) -> str:
    """Projects a canonical `stable_key` to a safe harness filename stem.

    Only `[A-Za-z0-9-_]`, collapsed dashes, bounded length — so a
    canonical key can never become a path traversal or an absolute
    path. Windows device names (`CON`, `NUL`, … — refused as path
    components, a collision vector) get a trailing underscore.
    Never inverted: the filename is not an identity."""
    cleaned = "".join(
        c if c.isascii() and (c.isalnum() or c in ("-", "_")) else "-" for c in stable_key
    )
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-_")[:120]
    if not cleaned:
        return "agent"
    if cleaned.lower() in _WINDOWS_RESERVED_STEMS:
        cleaned = f"{cleaned}_"
    return cleaned


def _yaml_single_line(value: str) -> str:
    """Folds free prose to one deterministic frontmatter line."""
    return " ".join(value.split())


def yaml_quoted(value: str) -> str:
    """Deterministic double-quoted YAML scalar for one line of prose."""
    single = _yaml_single_line(value)
    return '"' + single.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_frontmatter(fields: list[tuple[str, str | None]]) -> str:
    """Renders `---\\nkey: value\\n...---` skipping `None` values.

    Values arrive pre-rendered (`yaml_quoted(...)` or a bare token such
    as `subagent`); key order is the adapter's fixed mapping order."""
    lines = ["---"]
    for key, value in fields:
        if value is not None:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def prose_text(content: dict[str, object], *, default: str) -> str:
    """Extracts the P3 free-prose `text` of a rule/skill version.

    Falls back to a deterministic dump for non-textual shapes —
    never an invented sentence."""
    import json

    text = content.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return json.dumps(content, sort_keys=True, ensure_ascii=False)


def agent_summary(resolved: ResolvedAgentDefinition) -> str:
    """Best-effort human line for the harness `description` field.

    Order: version `title`, canonical `summary`, `intended_use`,
    then the stable key — the body always keeps the full text, so
    frontmatter folding never destroys information."""
    content = resolved.agent.content
    for key in ("summary", "intended_use"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return str(_yaml_single_line(value))
    if resolved.agent.title.strip():
        return str(_yaml_single_line(resolved.agent.title))
    return str(resolved.agent.stable_key)


def render_shared_body(
    resolved: ResolvedAgentDefinition,
    *,
    adapter_id: str,
    context: Any | None = None,
) -> tuple[str, list[AdapterWarning]]:
    """The canonical prose both harness adapters share (P10 gate).

    One builder, two envelopes: any difference between the Claude Code
    and OpenCode artifacts comes from the target format only — never
    from a divergent reading of the canonical definition. Reads the
    input without mutating it."""
    warnings: list[AdapterWarning] = []
    agent = resolved.agent
    lines: list[str] = [f"# {agent.title or agent.stable_key}", ""]

    summary = agent.content.get("summary")
    if isinstance(summary, str) and summary.strip():
        lines += [summary.strip(), ""]
    intended = agent.content.get("intended_use")
    if isinstance(intended, str) and intended.strip():
        lines += [f"Intended use: {intended.strip()}", ""]

    instructions = agent.content.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        lines += [instructions.strip(), ""]
    triggers = agent.content.get("triggers")
    if isinstance(triggers, list) and any(isinstance(t, str) and t.strip() for t in triggers):
        lines += ["## Triggers", ""]
        lines += [f"- {t.strip()}" for t in triggers if isinstance(t, str) and t.strip()]
        lines += [""]

    if resolved.rules:
        lines += ["## Rules", ""]
        for rule in resolved.rules:
            header = (
                f"### {rule.stable_key} "
                f"(v{rule.version}, {rule.scope.value}, {rule.version_origin.value})"
            )
            lines += [header, "", prose_text(rule.content, default=rule.stable_key).strip(), ""]
            if rule.deprecated:
                warnings.append(
                    AdapterWarning(
                        "deprecated_included",
                        f"rule {rule.stable_key!r} v{rule.version} deprecated but active",
                    )
                )
    if resolved.skills:
        lines += ["## Skills", ""]
        for skill in resolved.skills:
            header = (
                f"### {skill.stable_key} "
                f"(v{skill.version}, {skill.scope.value}, {skill.version_origin.value})"
            )
            lines += [header, "", prose_text(skill.content, default=skill.stable_key).strip(), ""]
            if skill.deprecated:
                warnings.append(
                    AdapterWarning(
                        "deprecated_included",
                        f"skill {skill.stable_key!r} v{skill.version} deprecated but active",
                    )
                )

    if resolved.model_profile is not None:
        requirements = resolved.model_profile.requirements
        dumped = requirements.model_dump(mode="json", exclude_none=True)
        active = {k: v for k, v in dumped.items() if v not in (False, [], {}, "")}
        lines += ["## Model requirements", ""]
        if active:
            for key in sorted(active):
                lines += [f"- {key}: {active[key]}"]
        else:
            lines += ["- none (no capability requirement)"]
        lines += [
            "",
            f"Profile: {resolved.model_profile.stable_key} "
            f"(v{resolved.model_profile.version}, {resolved.model_profile.scope.value}).",
            "Requirements only — the adapter never picks a concrete model.",
            "",
        ]

    if resolved.runtime is not None:
        target = resolved.runtime.target
        lines += ["## Runtime target", ""]
        for label, ref in (
            ("harness", target.harness_ref),
            ("provider", target.provider_ref),
            ("model", target.model_ref),
        ):
            lines += [f"- {label}: {ref if ref is not None else '(unspecified)'}"]
        lines += [
            f"- level: {resolved.runtime.level.value} "
            f"(matched {resolved.runtime.matched_kind.value}:"
            f"{resolved.runtime.matched_stable_key})",
            "",
        ]
        if target.model_ref is None:
            warnings.append(
                AdapterWarning(
                    "model_omitted_no_model_ref",
                    "resolved runtime names no concrete model; harness `model` field omitted",
                )
            )
    else:
        warnings.append(
            AdapterWarning(
                "no_runtime_target",
                "no runtime selected (valid P5 outcome); harness `model` field omitted",
            )
        )

    if context is not None:
        lines += ["## Context", ""]
        manifest = getattr(context, "manifest", None)
        if manifest is not None:
            sources = getattr(manifest, "sources", []) or []
            kinds = sorted({getattr(ref, "kind", "?") for ref in sources})
            lines += [
                f"Context package `{getattr(manifest, 'package_id', '?')}` "
                f"({len(sources)} source(s): {', '.join(kinds) if kinds else 'none'}).",
                "Generic P9 projection — source payloads travel with the caller, "
                "never rewritten for this harness.",
                "",
            ]
        else:
            lines += ["Context provided (unrecognized shape, echoed by reference only).", ""]

    if resolved.composed_agents:
        names = ", ".join(
            sorted(f"{r.kind.value}:{r.stable_key}" for r in resolved.composed_agents)
        )
        warnings.append(
            AdapterWarning(
                "composed_agents_not_expanded",
                f"composed agent refs preserved, not expanded: {names}",
            )
        )
    if resolved.workflows:
        names = ", ".join(sorted(f"{r.kind.value}:{r.stable_key}" for r in resolved.workflows))
        warnings.append(
            AdapterWarning(
                "workflows_not_expanded", f"workflow refs preserved, not expanded (P11): {names}"
            )
        )

    provenance = agent.provenance
    origin = provenance.version_origin.value if provenance.version_origin else "?"
    lines += [
        "## Provenance",
        "",
        f"- agent: {agent.stable_key} v{agent.version} ({provenance.source.value}, {origin})",
        f"- rules: {len(resolved.rules)}, skills: {len(resolved.skills)}",
        "",
        f"<!-- {MANAGED_MARKER} adapter={adapter_id!r} "
        f"stable-key={agent.stable_key!r} agent-version={agent.version} -->",
        "",
    ]
    return "\n".join(lines), warnings


def materialize(
    result: AdapterResult,
    root: Path,
    *,
    overwrite: bool = False,
    managed_dir: str | None = None,
) -> list[Path]:
    """Writes a complete `AdapterResult` under `root`, safely.

    Validate everything first (relative POSIX paths, containment in
    `root`, optional managed-dir confinement, no pre-existing file
    unless `overwrite`), then write each file via temp+replace so a
    failure never leaves a half-written file. Never deletes anything
    outside the artifact set — unmanaged user files are untouched."""
    if not root.is_dir():
        raise AdapterError(
            AdapterErrorCode.MATERIALIZATION_FAILED,
            f"root {str(root)!r} is not a directory",
            {"root": str(root)},
        )
    scope = managed_dir
    targets: list[tuple[AdapterArtifact, Path]] = []
    for artifact in result.artifacts:
        raw = artifact.path.replace("\\", "/")
        if not raw or raw.startswith("/") or raw.startswith("~"):
            raise AdapterError(
                AdapterErrorCode.MATERIALIZATION_FAILED,
                f"artifact path {artifact.path!r} is not a relative POSIX path",
                {"path": artifact.path},
            )
        candidate = (root / Path(*raw.split("/"))).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            raise AdapterError(
                AdapterErrorCode.MATERIALIZATION_FAILED,
                f"artifact path {artifact.path!r} escapes the root",
                {"path": artifact.path},
            ) from None
        if scope is not None:
            try:
                candidate.relative_to((root / Path(*scope.split("/"))).resolve())
            except ValueError:
                raise AdapterError(
                    AdapterErrorCode.MATERIALIZATION_FAILED,
                    f"artifact path {artifact.path!r} is outside managed dir {scope!r}",
                    {"path": artifact.path, "managed_dir": scope},
                ) from None
        if candidate.exists() and not overwrite:
            raise AdapterError(
                AdapterErrorCode.MATERIALIZATION_FAILED,
                f"refusing to overwrite existing {str(candidate)!r} without overwrite=True",
                {"path": artifact.path},
            )
        targets.append((artifact, candidate))

    written: list[Path] = []
    for artifact, candidate in targets:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        tmp = candidate.parent / f".{candidate.name}.studio-tmp"
        try:
            tmp.write_text(artifact.content, encoding="utf-8")
            tmp.replace(candidate)
        except AdapterError:
            raise
        except OSError as exc:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise AdapterError(
                AdapterErrorCode.MATERIALIZATION_FAILED,
                f"failed writing {artifact.path!r}: {exc}",
                {"path": artifact.path},
            ) from exc
        written.append(candidate)
    return written
