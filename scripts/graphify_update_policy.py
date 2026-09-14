"""Deterministic per-project Graphify update policy.

Loaded from ``<project_root>/.graphify-update.toml``. Decides, without any
LLM call, whether a changed file should go through AST extraction, semantic
(LLM) extraction, or be skipped entirely -- see
``docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/09_OBSIDIAN_GRAPHIFY.md``
for the rationale.

Pure stdlib (tomllib + fnmatch), no dependency on the ``graphify`` package,
so it can be imported and tested with the project's normal interpreter --
unlike ``graphify_incremental_update.py`` itself, which needs the
graphify-enabled interpreter.

Absent a policy file, ``load_policy`` returns ``None`` and callers must fall
back to legacy "everything is semantic-eligible" behaviour, so projects that
never adopted a policy file keep working exactly as before.
"""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass
from pathlib import Path

POLICY_FILENAME = ".graphify-update.toml"


@dataclass(frozen=True)
class Decision:
    action: str  # "ast" | "semantic" | "skip"
    reason: str


@dataclass(frozen=True)
class Policy:
    semantic_allowed: tuple[str, ...] = ()
    semantic_milestone_only: tuple[str, ...] = ()
    excluded_generated: tuple[str, ...] = ()
    excluded_skill_copies: tuple[str, ...] = ()
    excluded_transient: tuple[str, ...] = ()
    ast_excluded: tuple[str, ...] = ()


def _patterns(data: dict[str, object], *keys: str) -> tuple[str, ...]:
    node: object = data
    for key in keys:
        if not isinstance(node, dict):
            return ()
        node = node.get(key, {})
    if not isinstance(node, dict):
        return ()
    patterns = node.get("patterns", [])
    return tuple(patterns) if isinstance(patterns, list) else ()


def parse_policy(toml_text: str) -> Policy:
    data = tomllib.loads(toml_text)
    ast_exclude = data.get("ast", {}).get("exclude", [])
    return Policy(
        semantic_allowed=_patterns(data, "semantic", "allowed"),
        semantic_milestone_only=_patterns(data, "semantic", "milestone_only"),
        excluded_generated=_patterns(data, "exclude", "generated"),
        excluded_skill_copies=_patterns(data, "exclude", "skill_copies"),
        excluded_transient=_patterns(data, "exclude", "transient"),
        ast_excluded=tuple(ast_exclude) if isinstance(ast_exclude, list) else (),
    )


def load_policy(root: Path) -> Policy | None:
    """Return this project's policy, or None if it has no policy file."""
    path = root / POLICY_FILENAME
    if not path.exists():
        return None
    return parse_policy(path.read_text(encoding="utf-8"))


def _matches_any(rel_posix: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if fnmatch.fnmatch(rel_posix, pattern):
            return pattern
    return None


def classify(policy: Policy, rel_path: str, *, is_code: bool, milestone: bool = False) -> Decision:
    """Classify one changed file under `policy`.

    `is_code` marks a file with a native code extension (AST-eligible by
    Graphify's own extractor); anything else (docs, sidecars) is only
    semantic-eligible, and only when explicitly allow-listed.
    """
    rel_posix = rel_path.replace("\\", "/")

    skill_pat = _matches_any(rel_posix, policy.excluded_skill_copies)
    if skill_pat:
        return Decision("skip", f"excluded (skill copy, pattern {skill_pat!r})")

    generated_pat = _matches_any(rel_posix, policy.excluded_generated)
    if generated_pat:
        return Decision("skip", f"excluded (generated index, pattern {generated_pat!r})")

    transient_pat = _matches_any(rel_posix, policy.excluded_transient)
    if transient_pat:
        return Decision(
            "skip", f"excluded (transient/pilotage document, pattern {transient_pat!r})"
        )

    if is_code:
        ast_excl_pat = _matches_any(rel_posix, policy.ast_excluded)
        if ast_excl_pat:
            return Decision("skip", f"excluded from AST (pattern {ast_excl_pat!r})")
        return Decision("ast", "native code, deterministic AST extraction (0 token)")

    allowed_pat = _matches_any(rel_posix, policy.semantic_allowed)
    if allowed_pat:
        return Decision("semantic", f"semantic-allowed (pattern {allowed_pat!r})")

    milestone_pat = _matches_any(rel_posix, policy.semantic_milestone_only)
    if milestone_pat:
        if milestone:
            return Decision(
                "semantic", f"milestone-only, --milestone set (pattern {milestone_pat!r})"
            )
        return Decision(
            "skip",
            f"milestone-only document, no --milestone flag (pattern {milestone_pat!r})",
        )

    return Decision("skip", "not in semantic allowlist (default deny)")
