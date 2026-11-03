from __future__ import annotations

import ast
from pathlib import Path

_EXPECTED_IDENTITY_ALIASES = {
    "codex-cli": "codex",
    "codex-desktop": "codex",
    "claude-code": "claude",
    "claude-cli": "claude",
    "claude-desktop": "claude",
    "opencode-cli": "opencode",
    "opencode-desktop": "opencode",
}
_IDENTITY_MODULE = "packages/studio-contracts/src/studio_contracts/agent_identity.py"


def core_neutrality_source(path: Path, repo: Path) -> str:
    source = path.read_text(encoding="utf-8")
    if path.relative_to(repo).as_posix() != _IDENTITY_MODULE:
        return source
    assignments = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "HARNESS_IDENTITY_ALIASES"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1, "Expected exactly one identity alias assignment"
    assignment = assignments[0]
    assert len(assignment.targets) == 1, "Identity aliases must use a dedicated assignment"
    assert isinstance(assignment.value, ast.Dict), "Identity aliases must be a literal table"
    assert len(assignment.value.keys) == 7, "Expected exactly seven identity aliases"
    assert ast.literal_eval(assignment.value) == _EXPECTED_IDENTITY_ALIASES
    assert assignment.end_lineno is not None and assignment.end_col_offset is not None
    lines = source.encode("utf-8").splitlines(keepends=True)
    start = sum(map(len, lines[: assignment.lineno - 1])) + assignment.col_offset
    end = sum(map(len, lines[: assignment.end_lineno - 1])) + assignment.end_col_offset
    data = source.encode("utf-8")
    masked = bytes(char if char in (10, 13) else 32 for char in data[start:end])
    return (data[:start] + masked + data[end:]).decode("utf-8")
