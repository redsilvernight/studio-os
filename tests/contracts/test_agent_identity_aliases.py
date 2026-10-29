from __future__ import annotations

import pytest
from studio_contracts.agent_identity import logical_harness


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("codex", "codex"),
        ("codex-cli", "codex"),
        ("codex-desktop", "codex"),
        ("claude", "claude"),
        ("claude-code", "claude"),
        ("claude-cli", "claude"),
        ("claude-desktop", "claude"),
        ("opencode", "opencode"),
        ("opencode-cli", "opencode"),
        ("opencode-desktop", "opencode"),
        (" CODEX_DESKTOP ", "codex"),
        (" Claude_Code ", "claude"),
        (" OpenCode_CLI ", "opencode"),
    ],
)
def test_documented_aliases_resolve_to_logical_harness(value: str, expected: str) -> None:
    assert logical_harness(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "custom",
        "custom-cli",
        "custom-desktop",
        "custom-code",
        "codex-code",
        "opencode-code",
        "codex-cli-desktop",
        "codex-desktop-cli",
        "claude-code-cli",
        "claude-cli-desktop",
        "opencode-cli-desktop",
        "custom-code-desktop-cli",
    ],
)
def test_unregistered_harnesses_preserve_their_distinct_names(value: str) -> None:
    assert logical_harness(value) == value


def test_custom_harnesses_still_normalize_whitespace_case_and_underscores() -> None:
    assert logical_harness(" Custom_Desktop ") == "custom-desktop"
