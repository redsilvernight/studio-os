"""Library equivalence gate (P43): the Library rendering must equal the
committed harness projections.

The check never re-reads `.agents/` to build a projection: it publishes the
canonical resources in memory (`publish.build_publish_items`), then rebuilds
every managed harness file from those contents alone — rules through
`canonical.render_claude_rule`, agents through the local adapters on a
`LibrarySnapshot` resolved by `canonical.build_merged_resolved`, skills through
the committed skill mechanisms (`canonical.workflow_skill_projections_from` for
`.codex`/`.opencode`, verbatim `SKILL.md` + `references/` for `.claude`) — and
compares the result with the committed files.

Three consequences, all deliberate:

* a piece the Library content does not carry (the `studio-protocol` bootstrap
  rule, the `AGENTS.md`/`CLAUDE.md` managed blocks, hooks/MCP wiring) is
  reported as `excluded`, never dropped in silence;
* a skill the repository never projected into a harness (a harness only
  projects the workflow entry points, or a skill added after the last sync) is
  reported as `unprojected`: listed, not a gap — absence is the normal state;
* a field only the file holds (a rule `applies_to` before `rule/v2`, an agent
  `instructions`/`tools` before `agent_definition/v2`, a skill frontmatter key
  beyond `name`/`description`/`disable-model-invocation`, which `skill/v2`
  drops) shows up as a real gap
  with the diverging field or line named: that is exactly what the schema
  migration has to close.

Read-only: no network, no filesystem write, no server configuration.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from studio_client.publish import PublishItem

RULE_DIR = ".claude/rules"
"""Managed rule projection directory (one file per Library rule)."""

SKILL_DIRS: dict[str, str] = {
    "claude-code": ".claude/skills",
    "codex": ".codex/skills",
    "opencode": ".opencode/skills",
}
"""Harness id -> managed skills directory. Only the directories the repository
already has are inspected; `.codex`/`.opencode` only project the workflow
entry points (`canonical.workflow_skill_projections_from`), everything else is
reported `unprojected` rather than missing."""

_LIBRARY_ONLY_ROOT = (".studio-os", "library-equivalence")
"""Path that never holds canonical files: `build_merged_resolved` resolves every
piece from the injected `LibrarySnapshot` there, so the check cannot fall back
to — and silently echo — `.agents/`."""

_EXCLUDED_PATHS: dict[str, str] = {
    ".agents/rules/studio-protocol.md": "bootstrap protocol text, not a Library rule",
    ".agents/bootstrap.json": "bootstrap manifest (harness policy), outside the Library",
    "AGENTS.md": "managed rules block merged into a shared file",
    "CLAUDE.md": "managed pointer block merged into a shared file",
    ".claude/settings.json": "harness hooks/MCP wiring, per-machine configuration",
    ".mcp.json": "MCP wiring, per-machine configuration",
    ".codex/config.toml": "harness configuration, per-machine",
    ".opencode/opencode.json": "harness configuration, per-machine",
    "opencode.json": "harness configuration, per-machine",
}
"""Repository paths that carry state the Library never owns. Reported as
`excluded` whenever present."""

_EXCLUDED_KINDS = frozenset({"hook", "workflow"})
"""Publishable Library kinds with no repository file projection."""


class DifferenceNature(StrEnum):
    """Closed vocabulary of what an equivalence gap is."""

    MISSING = "missing"
    """Projected from the Library content, absent from the repository."""
    CONTENT = "content"
    """Both sides exist and their bytes differ."""
    UNEXPECTED = "unexpected"
    """Committed in a managed directory, reproducible from no Library content."""
    UNRESOLVED = "unresolved"
    """A Library content that cannot be projected at all (missing text, pin,
    invalid globs, unsafe key)."""
    UNPROJECTED = "unprojected"
    """No committed projection for this skill in this harness: the normal state
    for a skill the harness does not target. Listed, not compared."""
    EXCLUDED = "excluded"
    """Outside the Library surface by design: listed, never compared."""

    @property
    def blocking(self) -> bool:
        """True when the difference disproves the equivalence; absence and
        out-of-surface state are reported without failing the gate."""

        return self not in (DifferenceNature.UNPROJECTED, DifferenceNature.EXCLUDED)


@dataclass(frozen=True)
class Difference:
    """One equivalence gap: a repository-relative POSIX path, its nature and a
    short human-readable detail. Hashable, so callers can dedupe."""

    path: str
    nature: DifferenceNature
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "nature": self.nature.value, "detail": self.detail}


def check_equivalence(
    repo_root: Path | str, *, items: Sequence[PublishItem] | None = None
) -> list[Difference]:
    """Compare the projections rebuilt from Library contents with the committed
    ones, and return every gap.

    `items` injects the publish payloads explicitly (tests, or a caller that
    already built them); by default they come from `build_publish_items`, which
    reads `.agents/` once — after that, nothing but the item contents is used.
    Read-only, deterministic, never raises for a broken source (it is reported
    as `unresolved`)."""

    root = Path(repo_root)
    if items is None:
        from studio_client.publish import PublishError, build_publish_items

        try:
            library_items = build_publish_items(root)
        except (PublishError, FileNotFoundError, OSError, ValueError) as exc:
            return [Difference(".agents", DifferenceNature.UNRESOLVED, str(exc))]
    else:
        library_items = list(items)

    index: dict[tuple[str, str], PublishItem] = {
        (item.kind, item.stable_key): item for item in library_items
    }
    problems: list[Difference] = []
    sources = _skill_sources(index, problems)
    expected: dict[str, str] = {}
    expected.update(_agent_projections(root, index, problems))
    expected.update(_rule_projections(index, problems))
    expected.update(_skill_projections(root, sources, index, problems))

    differences = _compare(root, expected)
    differences.extend(problems)
    differences.extend(_unprojected(root, sources))
    differences.extend(_excluded(root, index))
    # One gap per (path, nature, detail): the same broken agent is seen once
    # per adapter directory otherwise.
    return list(dict.fromkeys(differences))


def _agent_projections(
    root: Path, index: dict[tuple[str, str], PublishItem], problems: list[Difference]
) -> dict[str, str]:
    """`.claude/agents/*.md`, `.codex/agents/*.toml`, `.opencode/agents/*.md`
    rebuilt from the agent Library contents, for every managed directory the
    repository actually has."""

    from studio_client.adapters import AdapterError, get_adapter, list_adapters

    files: dict[str, str] = {}
    for adapter_id in list_adapters():
        adapter = get_adapter(adapter_id)
        if not root.joinpath(*adapter.managed_dir.split("/")).is_dir():
            continue
        for (kind, key), item in sorted(index.items()):
            if kind != "agent":
                continue
            try:
                resolved = _library_resolved(root, item, index)
                result = adapter.translate(resolved)
            except (AdapterError, KeyError, ValueError) as exc:
                problems.append(
                    Difference(
                        f".agents/definitions/{key}.md",
                        DifferenceNature.UNRESOLVED,
                        f"{adapter_id}: {exc}",
                    )
                )
                continue
            for artifact in result.artifacts:
                files[artifact.path.replace("\\", "/")] = artifact.content
    return files


def _library_resolved(
    root: Path, item: PublishItem, index: dict[tuple[str, str], PublishItem]
) -> Any:
    """`ResolvedAgentDefinition` carrying only Library content: the agent head,
    its pinned rules/skills and the requirements of its pinned model profile."""

    from studio_contracts.library import (
        BindingRelation,
        CapabilityRequirement,
        LibraryKind,
        LibraryScope,
        VersionOrigin,
    )
    from studio_contracts.resolution import ResolvedAgent, ResolvedRule, ResolvedSkill

    from studio_client.canonical import (
        LibrarySnapshot,
        _namespace,
        _prov,
        build_merged_resolved,
    )

    rules: dict[str, Any] = {}
    skills: dict[str, Any] = {}
    requirements = CapabilityRequirement()
    for pin_kind, pin_key in item.pins:
        pinned = index.get((pin_kind, pin_key))
        if pinned is None:
            raise ValueError(f"pins {pin_kind} {pin_key!r} that no publish item carries")
        if pin_kind == "rule":
            rules[pin_key] = ResolvedRule(
                resource_id=_namespace("resource", pin_key),
                stable_key=pin_key,
                scope=LibraryScope.STUDIO,
                version=1,
                version_origin=VersionOrigin.ACTIVE,
                title=pin_key,
                content={"content_schema": _schema(pinned, "rule"), "text": _text(pinned)},
            )
        elif pin_kind == "skill":
            skills[pin_key] = ResolvedSkill(
                resource_id=_namespace("resource", pin_key),
                stable_key=pin_key,
                scope=LibraryScope.STUDIO,
                version=1,
                version_origin=VersionOrigin.ACTIVE,
                title=pinned.title,
                content={"content_schema": _schema(pinned, "skill"), "text": _text(pinned)},
                provenance=_prov(pin_key, BindingRelation.USES_SKILL),
            )
        elif pin_kind == "model_profile":
            requirements = _requirements(pinned)

    head = ResolvedAgent(
        resource_id=_namespace("resource", f"agent:{item.stable_key}"),
        kind=LibraryKind.AGENT_DEFINITION,
        stable_key=item.stable_key,
        scope=LibraryScope.STUDIO,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        title=item.title,
        content=dict(item.content),
        provenance=_prov(f"agent:{item.stable_key}"),
    )
    snapshot = LibrarySnapshot(agent=head, rules=rules, skills=skills, requirements=requirements)
    resolved = build_merged_resolved(
        root.joinpath(*_LIBRARY_ONLY_ROOT), item.stable_key, library=snapshot
    )
    return _head_from_content(resolved, item.content)


def _head_from_content(resolved: Any, content: dict[str, object]) -> Any:
    """`build_merged_resolved` only knows the v1 head of a Library-only agent.
    The v2 fields travel in the same version content, so they are restored
    here — the Library, never a local file, stays the source."""

    merged = dict(resolved.agent.content)
    for field, default in (
        ("summary", ""),
        ("intended_use", ""),
        ("instructions", ""),
        ("triggers", []),
        ("edit_policy", "deny"),
        ("tools", []),
    ):
        value = content.get(field)
        merged[field] = default if value is None else value
    return resolved.model_copy(
        update={"agent": resolved.agent.model_copy(update={"content": merged})}
    )


def _rule_projections(
    index: dict[tuple[str, str], PublishItem], problems: list[Difference]
) -> dict[str, str]:
    """`.claude/rules/<key>.md` rebuilt from each rule version (`applies_to`
    plus the body: `rule/v2`, empty globs meaning a global rule)."""

    from studio_client.canonical import render_claude_rule

    files: dict[str, str] = {}
    for (kind, key), item in sorted(index.items()):
        if kind != "rule":
            continue
        try:
            applies_to = item.content.get("applies_to") or []
            if not isinstance(applies_to, list) or not all(
                isinstance(glob, str) for glob in applies_to
            ):
                raise ValueError("applies_to must be a list of globs")
            files[f"{RULE_DIR}/{key}.md"] = render_claude_rule(key, list(applies_to), _text(item))
        except ValueError as exc:
            problems.append(
                Difference(f".agents/rules/{key}.md", DifferenceNature.UNRESOLVED, str(exc))
            )
    return files


def _skill_sources(
    index: dict[tuple[str, str], PublishItem], problems: list[Difference]
) -> dict[str, str]:
    """Verbatim `SKILL.md` text rebuilt from each skill version.

    `skill/v2` carries the body with the frontmatter stripped, the
    `disable_model_invocation` flag and `files[]` for references; the
    canonical projection is the raw file, so the frontmatter is restored
    exactly the way `projection_source` derives it from a resolved skill
    (`name`, the description the publisher read, plus
    `disable-model-invocation` when the Library content carries it).
    Anything else the committed file holds beyond those keys is a real
    loss, reported by `_compare`."""

    from studio_contracts.library import LibraryScope, VersionOrigin
    from studio_contracts.resolution import ResolvedSkill

    from studio_client.canonical import _namespace, _prov
    from studio_client.projection_source import _skill_source

    sources: dict[str, str] = {}
    for (kind, key), item in sorted(index.items()):
        if kind != "skill":
            continue
        try:
            resolved = ResolvedSkill(
                resource_id=_namespace("resource", key),
                stable_key=key,
                scope=LibraryScope.STUDIO,
                version=1,
                version_origin=VersionOrigin.ACTIVE,
                title=item.title,
                content={
                    "text": _text(item),
                    "disable_model_invocation": bool(item.content.get("disable_model_invocation")),
                },
                provenance=_prov(key),
            )
            sources[key] = _skill_source(resolved)
        except ValueError as exc:
            problems.append(
                Difference(f".agents/skills/{key}/SKILL.md", DifferenceNature.UNRESOLVED, str(exc))
            )
    return sources


def _skill_projections(
    root: Path,
    sources: dict[str, str],
    index: dict[tuple[str, str], PublishItem],
    problems: list[Difference],
) -> dict[str, str]:
    """Committed skill projections, rebuilt from the Library sources alone.

    `.codex`/`.opencode` follow `canonical.workflow_skill_projections_from` (the
    workflow entry points, verbatim). `.claude` copies every skill verbatim,
    `references/` included — never the dashboard install envelope
    (`skill_sync.render_skill`), which no repository commits."""

    from studio_client.canonical import workflow_skill_projections_from

    files: dict[str, str] = {}
    for relative, text in workflow_skill_projections_from(sources).items():
        harness_dir = "/".join(relative.split("/")[:2])
        if root.joinpath(*harness_dir.split("/")).is_dir():
            files[relative] = text
    claude_dir = SKILL_DIRS["claude-code"]
    if not root.joinpath(*claude_dir.split("/")).is_dir():
        return files
    for key, source in sources.items():
        files[f"{claude_dir}/{key}/SKILL.md"] = source
        item = index[("skill", key)]
        try:
            aux_files = _aux_files(item)
        except ValueError as exc:
            problems.append(
                Difference(f"{claude_dir}/{key}", DifferenceNature.UNRESOLVED, str(exc))
            )
            continue
        for aux_path, aux_text in aux_files:
            files[f"{claude_dir}/{key}/{aux_path}"] = aux_text
    return files


def _unprojected(root: Path, sources: dict[str, str]) -> list[Difference]:
    """Skills the repository never projected into a harness it does target:
    absence is the normal state of a skill outside that harness, never a gap."""

    unprojected: list[Difference] = []
    for harness_dir in sorted(set(SKILL_DIRS.values())):
        if not root.joinpath(*harness_dir.split("/")).is_dir():
            continue
        for key in sorted(sources):
            if root.joinpath(*f"{harness_dir}/{key}".split("/")).is_dir():
                continue
            unprojected.append(
                Difference(
                    f"{harness_dir}/{key}",
                    DifferenceNature.UNPROJECTED,
                    "no committed projection for this skill in this harness",
                )
            )
    return unprojected


def _aux_files(item: PublishItem) -> tuple[tuple[str, str], ...]:
    raw = item.content.get("files") or []
    if not isinstance(raw, list):
        raise ValueError("skill files must be a list")
    files: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("skill files entries must be objects")
        path, text = entry.get("path"), entry.get("text")
        if not isinstance(path, str) or not isinstance(text, str):
            raise ValueError("skill files entries need string 'path' and 'text'")
        files.append((path, text))
    return tuple(files)


def _requirements(item: PublishItem) -> Any:
    from studio_contracts.library import CapabilityRequirement

    raw = item.content.get("requirements") or {}
    if not isinstance(raw, dict):
        raise ValueError(f"model_profile {item.stable_key!r}: requirements must be an object")
    return CapabilityRequirement.model_validate(raw)


def _compare(root: Path, expected: dict[str, str]) -> list[Difference]:
    """Byte comparison (LF-normalized, like every other drift check here)
    between the Library projection and the committed files, plus the files no
    Library content reproduces.

    A file missing from a managed skills directory whose skill directory is
    absent is not a gap: nothing was ever projected (see `_unprojected`).
    """

    differences: list[Difference] = []
    for relative, content in sorted(expected.items()):
        target = root.joinpath(*relative.split("/"))
        if not target.is_file():
            skill_dir = _committed_skill_dir(root, relative)
            if skill_dir is not None and not skill_dir.is_dir():
                continue
            differences.append(
                Difference(
                    relative,
                    DifferenceNature.MISSING,
                    "projected from the Library content, absent from the repository",
                )
            )
            continue
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            differences.append(
                Difference(relative, DifferenceNature.CONTENT, f"unreadable as UTF-8: {exc}")
            )
            continue
        if _normalize(current) != _normalize(content):
            semantic = _committed_skill_dir(root, relative) is not None
            detail = _describe(content, current, semantic=semantic)
            if detail is None:
                # Skills only: identical fields and body, the raw bytes differ
                # by frontmatter quoting — a rendering detail, not a loss.
                continue
            differences.append(Difference(relative, DifferenceNature.CONTENT, detail))
    for relative in sorted(_managed_files(root) - set(expected)):
        differences.append(
            Difference(
                relative,
                DifferenceNature.UNEXPECTED,
                "no Library content reproduces this committed file",
            )
        )
    return differences


def _committed_skill_dir(root: Path, relative: str) -> Path | None:
    """The `<harness>/skills/<key>` directory a managed relative path belongs
    to, or None for a path outside the skills projections."""

    for harness_dir in SKILL_DIRS.values():
        prefix = f"{harness_dir}/"
        if relative.startswith(prefix):
            key = relative[len(prefix) :].split("/", 1)[0]
            return root.joinpath(*f"{harness_dir}/{key}".split("/"))
    return None


def _describe(expected: str, committed: str, *, semantic: bool = False) -> str | None:
    """Human diagnosis of a divergent projection: the frontmatter keys the
    Library cannot carry, the fields whose value differs and the first body
    line that diverges — never an opaque hash.

    `semantic=True` (skills) compares fields and body: a file whose parsed
    content matches but whose raw bytes differ only by frontmatter quoting is
    not a loss, and returns None."""

    expected_fields, expected_body = _frontmatter(expected)
    committed_fields, committed_body = _frontmatter(committed)
    details: list[str] = []
    for field in sorted(set(committed_fields) - set(expected_fields)):
        details.append(f"frontmatter field {field!r} is not carried by the Library content")
    for field in sorted(set(expected_fields) - set(committed_fields)):
        details.append(f"frontmatter field {field!r} is missing from the committed file")
    for field in sorted(set(expected_fields) & set(committed_fields)):
        if expected_fields[field] != committed_fields[field]:
            details.append(
                f"frontmatter field {field!r} differs: "
                f"committed {committed_fields[field]!r} library {expected_fields[field]!r}"
            )
    if expected_body != committed_body:
        details.append(_first_divergent_line(expected_body, committed_body))
    if details:
        return "; ".join(details)
    return None if semantic else "contents differ"


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """`(fields, body)` of a projected file, body normalized like the canonical
    reader does (`strip()` + one newline), so only real content diverges."""

    normalized = _normalize(text)
    match = _FRONTMATTER_RE.match(normalized)
    if match is None:
        return {}, normalized
    try:
        fields = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, normalized
    if not isinstance(fields, dict):
        return {}, normalized
    return fields, match.group(2).strip() + "\n"


def _first_divergent_line(expected: str, committed: str) -> str:
    expected_lines, committed_lines = expected.split("\n"), committed.split("\n")
    for number, (expected_line, committed_line) in enumerate(
        zip(expected_lines, committed_lines, strict=False), start=1
    ):
        if expected_line != committed_line:
            return (
                f"first divergent body line {number}: "
                f"committed {_short(committed_line)} library {_short(expected_line)}"
            )
    return (
        f"body line count differs: committed {len(committed_lines)} library {len(expected_lines)}"
    )


def _short(line: str, limit: int = 80) -> str:
    return repr(line if len(line) <= limit else line[: limit - 1] + "…")


def _managed_files(root: Path) -> set[str]:
    """Every committed file in a managed projection directory."""

    from studio_client.adapters import get_adapter, list_adapters

    directories = [RULE_DIR, *(get_adapter(adapter).managed_dir for adapter in list_adapters())]
    directories.extend(SKILL_DIRS.values())
    found: set[str] = set()
    for relative in directories:
        base = root.joinpath(*relative.split("/"))
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                found.add(path.relative_to(root).as_posix())
    return found


def _excluded(root: Path, index: dict[tuple[str, str], PublishItem]) -> list[Difference]:
    """State the Library does not own, listed so it is never ignored silently."""

    excluded: list[Difference] = []
    for relative, reason in sorted(_EXCLUDED_PATHS.items()):
        if root.joinpath(*relative.split("/")).exists():
            excluded.append(Difference(relative, DifferenceNature.EXCLUDED, reason))
    for kind, key in sorted(index):
        if kind in _EXCLUDED_KINDS:
            excluded.append(
                Difference(
                    f"{kind}/{key}",
                    DifferenceNature.EXCLUDED,
                    "publishable Library kind with no repository file projection",
                )
            )
    return excluded


def _text(item: PublishItem) -> str:
    text = item.content.get("text")
    if not isinstance(text, str):
        raise ValueError(f"{item.kind} {item.stable_key!r} version has no text content")
    return text


def _schema(item: PublishItem, kind: str) -> str:
    schema = item.content.get("content_schema")
    if isinstance(schema, str) and schema:
        return schema
    return f"studio.library.{kind}/v1"


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n")
