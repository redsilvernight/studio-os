from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client.harness.base import AdapterRefusal, DetectionState, HarnessAdapter
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.opencode import OpenCodeAdapter

from tests.harness.support import CLAUDE_VERSION_LINE, MCP_URL, Rig, install_fake, make_rig


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def _apply(adapter: HarnessAdapter, rig: Rig) -> None:
    for edit in adapter.plan(rig.context):
        (rig.root / edit.target).write_bytes(edit.after)


CASES = [
    pytest.param(ClaudeCodeAdapter(), ".mcp.json", ("mcpServers", "studio-os"), id="claude"),
    pytest.param(OpenCodeAdapter(), "opencode.json", ("mcp", "studio-os"), id="opencode"),
]


def test_identity_is_declared_by_the_adapter_alone() -> None:
    assert ClaudeCodeAdapter.adapter_id == "claude-code"
    assert OpenCodeAdapter.adapter_id == "opencode"


@pytest.mark.parametrize(("adapter", "target", "path"), CASES)
def test_not_installed_when_no_executable(
    adapter: HarnessAdapter, target: str, path: tuple[str, ...], tmp_path: Path
) -> None:
    rig = make_rig(tmp_path, claude=False, opencode=False)
    detection = adapter.detect(rig.context)
    assert detection.state is DetectionState.NOT_INSTALLED
    assert detection.reason == "executable_not_found"


@pytest.mark.parametrize(("adapter", "target", "path"), CASES)
def test_installed_without_configuration(
    adapter: HarnessAdapter, target: str, path: tuple[str, ...], rig: Rig
) -> None:
    detection = adapter.detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_MISSING
    assert detection.version in {"2.1.272", "1.18.31"}
    assert not (rig.root / target).exists()


@pytest.mark.parametrize(("adapter", "target", "path"), CASES)
def test_plan_creates_the_file_then_detects_configured(
    adapter: HarnessAdapter, target: str, path: tuple[str, ...], rig: Rig
) -> None:
    edits = adapter.plan(rig.context)
    assert [edit.target for edit in edits] == [target]
    assert edits[0].kind.value == "create"
    assert not (rig.root / target).exists(), "plan never writes"
    _apply(adapter, rig)
    data = json.loads((rig.root / target).read_text(encoding="utf-8"))
    assert data[path[0]][path[1]]["url"] == MCP_URL
    assert adapter.detect(rig.context).state is DetectionState.CONFIGURED
    assert adapter.plan(rig.context) == [], "a second plan is a no-op"


@pytest.mark.parametrize(("adapter", "target", "path"), CASES)
def test_entry_references_the_token_and_never_holds_it(
    adapter: HarnessAdapter, target: str, path: tuple[str, ...], rig: Rig
) -> None:
    rig.env["STUDIO_MCP_MACHINE_TOKEN"] = "sk-SECRET-VALUE-123456"
    _apply(adapter, rig)
    text = (rig.root / target).read_text(encoding="utf-8")
    assert "STUDIO_MCP_MACHINE_TOKEN" in text
    assert "SECRET-VALUE" not in text
    for forbidden in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "apiKey", "api_key"):
        assert forbidden not in text


@pytest.mark.parametrize(("adapter", "target", "path"), CASES)
def test_other_servers_and_settings_are_preserved(
    adapter: HarnessAdapter, target: str, path: tuple[str, ...], rig: Rig
) -> None:
    original = {
        path[0]: {"other": {"command": "npx", "args": ["x"]}},
        "theme": "dark",
        "permissions": {"allow": ["Bash(ls)"]},
    }
    (rig.root / target).write_text(json.dumps(original, indent=2), encoding="utf-8")
    edits = adapter.plan(rig.context)
    assert edits[0].kind.value == "modify"
    (rig.root / target).write_bytes(edits[0].after)
    data = json.loads((rig.root / target).read_text(encoding="utf-8"))
    assert data[path[0]]["other"] == original[path[0]]["other"]
    assert data["theme"] == "dark"
    assert data["permissions"] == original["permissions"]
    assert adapter.detect(rig.context).state is DetectionState.CONFIGURED


def test_opencode_preserves_comments_and_trailing_commas(rig: Rig) -> None:
    text = (
        "{\n"
        "  // my providers\n"
        '  "provider": {"x": {"options": {"k": 1}}}, // keep\n'
        '  "mcp": {\n'
        '    "other": {"type": "local", "command": ["a"]},\n'
        "  },\n"
        "}\n"
    )
    (rig.root / "opencode.jsonc").write_text(text, encoding="utf-8", newline="")
    edits = OpenCodeAdapter().plan(rig.context)
    after = edits[0].after.decode("utf-8")
    assert "// my providers" in after
    assert "// keep" in after
    assert '"other"' in after
    assert "studio-os" in after


def test_a_differing_entry_is_updated_not_duplicated(rig: Rig) -> None:
    (rig.root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"studio-os": {"type": "http", "url": "https://old/mcp"}}}),
        encoding="utf-8",
    )
    adapter = ClaudeCodeAdapter()
    detection = adapter.detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_MISSING
    assert detection.reason == "entry_differs"
    (rig.root / ".mcp.json").write_bytes(adapter.plan(rig.context)[0].after)
    text = (rig.root / ".mcp.json").read_text(encoding="utf-8")
    assert text.count("studio-os") == 1
    assert MCP_URL in text


@pytest.mark.parametrize(("adapter", "target", "path"), CASES)
def test_malformed_config_fails_closed(
    adapter: HarnessAdapter, target: str, path: tuple[str, ...], rig: Rig
) -> None:
    (rig.root / target).write_text('{"mcpServers": {', encoding="utf-8")
    assert adapter.detect(rig.context).state is DetectionState.CONFIGURATION_INVALID
    with pytest.raises(AdapterRefusal):
        adapter.plan(rig.context)
    assert (rig.root / target).read_text(encoding="utf-8") == '{"mcpServers": {'


def test_unexpected_container_shape_fails_closed(rig: Rig) -> None:
    (rig.root / ".mcp.json").write_text('{"mcpServers": []}', encoding="utf-8")
    assert ClaudeCodeAdapter().detect(rig.context).state is DetectionState.CONFIGURATION_INVALID


def test_ambiguous_opencode_files_fail_closed(rig: Rig) -> None:
    (rig.root / "opencode.json").write_text("{}", encoding="utf-8")
    (rig.root / "opencode.jsonc").write_text("{}", encoding="utf-8")
    detection = OpenCodeAdapter().detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_INVALID
    assert detection.reason == "ambiguous_config"


@pytest.mark.parametrize(
    ("adapter", "name", "line"),
    [
        (ClaudeCodeAdapter(), "claude", "3.0.0 (Claude Code)"),
        (ClaudeCodeAdapter(), "claude", "1.9.9 (Claude Code)"),
        (OpenCodeAdapter(), "opencode", "2.0.0"),
        (OpenCodeAdapter(), "opencode", "0.9.0"),
    ],
)
def test_unknown_major_version_is_incompatible(
    adapter: HarnessAdapter, name: str, line: str, rig: Rig
) -> None:
    install_fake(rig.bin_dir, name, line)
    detection = adapter.detect(rig.context)
    assert detection.state is DetectionState.INCOMPATIBLE
    assert detection.reason == "unsupported_version"
    with pytest.raises(AdapterRefusal):
        adapter.plan(rig.context)


@pytest.mark.parametrize(
    ("adapter", "name"), [(ClaudeCodeAdapter(), "claude"), (OpenCodeAdapter(), "opencode")]
)
def test_a_binary_that_is_not_the_harness_is_unavailable(
    adapter: HarnessAdapter, name: str, rig: Rig
) -> None:
    install_fake(rig.bin_dir, name, "hello from something else")
    detection = adapter.detect(rig.context)
    assert detection.state is DetectionState.UNAVAILABLE
    assert detection.reason == "unexpected_output"


def test_a_failing_probe_is_unavailable(rig: Rig) -> None:
    install_fake(rig.bin_dir, "claude", CLAUDE_VERSION_LINE, exit_code=3)
    detection = ClaudeCodeAdapter().detect(rig.context)
    assert detection.state is DetectionState.UNAVAILABLE
    assert detection.reason == "probe_failed"


def test_the_two_harnesses_are_independent(rig: Rig) -> None:
    _apply(ClaudeCodeAdapter(), rig)
    assert ClaudeCodeAdapter().detect(rig.context).state is DetectionState.CONFIGURED
    assert OpenCodeAdapter().detect(rig.context).state is DetectionState.CONFIGURATION_MISSING
