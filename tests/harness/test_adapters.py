from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client.harness.base import AdapterRefusal, DetectionState, HarnessAdapter
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.redaction import fingerprint

from tests.harness.support import (
    CLAUDE_VERSION_LINE,
    MCP_URL,
    OPENCODE_CONFIG,
    Rig,
    install_fake,
    make_rig,
)

TOKEN = "sk_test_adapter_token_0123456789"


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def _adapter(rig: Rig, adapter_id: str) -> HarnessAdapter:
    if adapter_id == "claude-code":
        return ClaudeCodeAdapter(cli_runner=rig.cli)
    return OpenCodeAdapter()


def _configure(adapter: HarnessAdapter, rig: Rig, token: str = TOKEN) -> None:
    """What the service does once it holds a dedicated credential."""
    plan = adapter.plan(rig.context)
    for edit in plan.workspace_edits:
        (rig.root / edit.target).write_bytes(edit.after)
    adapter.write_user_entry(rig.context, adapter.build_entry(MCP_URL, token))


CASES = [
    pytest.param("claude-code", ".mcp.json", ".claude.json", "mcpServers", id="claude"),
    pytest.param("opencode", "opencode.json", OPENCODE_CONFIG, "mcp", id="opencode"),
]


def test_identity_is_declared_by_the_adapter_alone() -> None:
    assert ClaudeCodeAdapter.adapter_id == "claude-code"
    assert OpenCodeAdapter.adapter_id == "opencode"


@pytest.mark.parametrize(("adapter_id", "project", "user", "container"), CASES)
def test_not_installed_when_no_executable(
    adapter_id: str, project: str, user: str, container: str, tmp_path: Path
) -> None:
    rig = make_rig(tmp_path, claude=False, opencode=False)
    detection = _adapter(rig, adapter_id).detect(rig.context)
    assert detection.state is DetectionState.NOT_INSTALLED
    assert detection.reason == "executable_not_found"


@pytest.mark.parametrize(("adapter_id", "project", "user", "container"), CASES)
def test_installed_without_configuration(
    adapter_id: str, project: str, user: str, container: str, rig: Rig
) -> None:
    detection = _adapter(rig, adapter_id).detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_MISSING
    assert detection.version in {"2.1.272", "1.18.31"}
    assert not (rig.root / project).exists()


@pytest.mark.parametrize(("adapter_id", "project", "user", "container"), CASES)
def test_plan_targets_the_user_config_then_detects_configured(
    adapter_id: str, project: str, user: str, container: str, rig: Rig
) -> None:
    adapter = _adapter(rig, adapter_id)
    plan = adapter.plan(rig.context)
    assert plan.workspace_edits == []
    assert plan.user_entry is not None
    assert plan.user_entry.target == user
    assert plan.user_entry.kind.value == "create"
    assert not (rig.home / user).exists(), "plan never writes"
    assert TOKEN.encode() not in plan.user_entry.after
    _configure(adapter, rig)
    assert not (rig.root / project).exists(), "nothing is written in the workspace"
    data = json.loads((rig.home / user).read_text(encoding="utf-8"))
    assert data[container]["studio-os"]["url"] == MCP_URL
    detection = adapter.detect(rig.context)
    assert detection.state is DetectionState.CONFIGURED
    assert detection.credential_fingerprint == fingerprint(TOKEN)
    assert adapter.plan(rig.context).empty, "a second plan is a no-op"
    assert adapter.plan(rig.context, renew=True).user_entry is not None


@pytest.mark.parametrize(("adapter_id", "project", "user", "container"), CASES)
def test_the_plan_is_independent_of_the_credential(
    adapter_id: str, project: str, user: str, container: str, rig: Rig
) -> None:
    adapter = _adapter(rig, adapter_id)
    _configure(adapter, rig, "sk_first")
    first = adapter.plan(rig.context, renew=True).user_entry
    _configure(adapter, rig, "sk_second")
    second = adapter.plan(rig.context, renew=True).user_entry
    assert first is not None and second is not None
    assert first.before == second.before
    assert b"sk_first" not in first.before and b"sk_second" not in second.before
    for forbidden in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "apiKey", "api_key"):
        assert forbidden.encode() not in first.after


@pytest.mark.parametrize(("adapter_id", "project", "user", "container"), CASES)
def test_other_servers_and_settings_are_preserved(
    adapter_id: str, project: str, user: str, container: str, rig: Rig
) -> None:
    original = {
        container: {"other": {"command": "npx", "args": ["x"]}},
        "theme": "dark",
        "permissions": {"allow": ["Bash(ls)"]},
    }
    path = rig.home / user
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(original, indent=2), encoding="utf-8")
    adapter = _adapter(rig, adapter_id)
    _configure(adapter, rig)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[container]["other"] == original[container]["other"]
    assert data["theme"] == "dark"
    assert data["permissions"] == original["permissions"]
    assert adapter.detect(rig.context).state is DetectionState.CONFIGURED


@pytest.mark.parametrize(("adapter_id", "project", "user", "container"), CASES)
def test_a_project_entry_is_migrated_and_other_servers_kept(
    adapter_id: str, project: str, user: str, container: str, rig: Rig
) -> None:
    original = {
        container: {
            "studio-os": {"type": "http", "url": MCP_URL},
            "other": {"command": "npx"},
        },
        "theme": "dark",
    }
    (rig.root / project).write_text(json.dumps(original), encoding="utf-8")
    adapter = _adapter(rig, adapter_id)
    detection = adapter.detect(rig.context)
    assert detection.reason == "project_entry_migration"
    [edit] = adapter.plan(rig.context).workspace_edits
    assert edit.target == project and edit.kind.value == "modify"
    _configure(adapter, rig)
    data = json.loads((rig.root / project).read_text(encoding="utf-8"))
    assert data == {container: {"other": {"command": "npx"}}, "theme": "dark"}
    assert adapter.detect(rig.context).state is DetectionState.CONFIGURED


@pytest.mark.parametrize(("adapter_id", "project", "user", "container"), CASES)
def test_a_project_entry_holding_a_secret_is_never_touched(
    adapter_id: str, project: str, user: str, container: str, rig: Rig
) -> None:
    text = json.dumps(
        {container: {"studio-os": {"url": MCP_URL, "headers": {"Authorization": "Bearer x1"}}}}
    )
    (rig.root / project).write_text(text, encoding="utf-8")
    adapter = _adapter(rig, adapter_id)
    detection = adapter.detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_INVALID
    assert detection.reason == "project_entry_conflict"
    with pytest.raises(AdapterRefusal):
        adapter.plan(rig.context)
    assert (rig.root / project).read_text(encoding="utf-8") == text


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
    path = rig.home / ".config/opencode/opencode.jsonc"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8", newline="")
    _configure(OpenCodeAdapter(), rig)
    after = path.read_text(encoding="utf-8")
    assert "// my providers" in after
    assert "// keep" in after
    assert '"other"' in after
    assert "studio-os" in after
    assert not (rig.home / OPENCODE_CONFIG).exists()


def test_a_differing_entry_is_updated_not_duplicated(rig: Rig) -> None:
    rig.claude_config.write_text(
        json.dumps({"mcpServers": {"studio-os": {"type": "http", "url": "https://old/mcp"}}}),
        encoding="utf-8",
    )
    adapter = ClaudeCodeAdapter(cli_runner=rig.cli)
    detection = adapter.detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_MISSING
    assert detection.reason == "entry_differs"
    _configure(adapter, rig)
    text = rig.claude_config.read_text(encoding="utf-8")
    assert text.count("studio-os") == 1
    assert MCP_URL in text
    assert [call[:2] for call in rig.cli.calls] == [("mcp", "remove"), ("mcp", "add-json")]


def test_an_env_reference_is_reported_as_a_token_reference(rig: Rig) -> None:
    rig.claude_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "studio-os": {
                        "type": "http",
                        "url": MCP_URL,
                        "headers": {"Authorization": "Bearer ${STUDIO_MCP_MACHINE_TOKEN}"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    detection = ClaudeCodeAdapter(cli_runner=rig.cli).detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_MISSING
    assert detection.reason == "token_reference"


def test_a_local_scope_entry_shadowing_the_user_one_fails_closed(rig: Rig) -> None:
    rig.claude_config.write_text(
        json.dumps({"projects": {str(rig.root): {"mcpServers": {"studio-os": {"url": "x"}}}}}),
        encoding="utf-8",
    )
    detection = ClaudeCodeAdapter(cli_runner=rig.cli).detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_INVALID
    assert detection.reason == "local_entry_conflict"


@pytest.mark.parametrize(("adapter_id", "project", "user", "container"), CASES)
def test_malformed_config_fails_closed(
    adapter_id: str, project: str, user: str, container: str, rig: Rig
) -> None:
    (rig.root / project).write_text('{"mcpServers": {', encoding="utf-8")
    adapter = _adapter(rig, adapter_id)
    assert adapter.detect(rig.context).state is DetectionState.CONFIGURATION_INVALID
    with pytest.raises(AdapterRefusal):
        adapter.plan(rig.context)
    assert (rig.root / project).read_text(encoding="utf-8") == '{"mcpServers": {'


@pytest.mark.parametrize(("adapter_id", "project", "user", "container"), CASES)
def test_malformed_user_config_fails_closed(
    adapter_id: str, project: str, user: str, container: str, rig: Rig
) -> None:
    path = rig.home / user
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"mcp": {', encoding="utf-8")
    adapter = _adapter(rig, adapter_id)
    assert adapter.detect(rig.context).state is DetectionState.CONFIGURATION_INVALID
    with pytest.raises(AdapterRefusal):
        adapter.plan(rig.context)
    assert path.read_text(encoding="utf-8") == '{"mcp": {'


def test_unexpected_container_shape_fails_closed(rig: Rig) -> None:
    (rig.root / ".mcp.json").write_text('{"mcpServers": []}', encoding="utf-8")
    detection = ClaudeCodeAdapter(cli_runner=rig.cli).detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_INVALID


def test_ambiguous_opencode_files_fail_closed(rig: Rig) -> None:
    directory = rig.home / ".config/opencode"
    directory.mkdir(parents=True)
    (directory / "opencode.json").write_text("{}", encoding="utf-8")
    (directory / "opencode.jsonc").write_text("{}", encoding="utf-8")
    detection = OpenCodeAdapter().detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_INVALID
    assert detection.reason == "ambiguous_config"


def test_an_opencode_config_home_outside_home_is_refused(rig: Rig, tmp_path: Path) -> None:
    rig.env["XDG_CONFIG_HOME"] = str(tmp_path / "elsewhere")
    detection = OpenCodeAdapter().detect(rig.context)
    assert detection.state is DetectionState.CONFIGURATION_INVALID
    assert detection.reason == "unsupported_config_home"


@pytest.mark.parametrize(
    ("adapter_id", "name", "line"),
    [
        ("claude-code", "claude", "3.0.0 (Claude Code)"),
        ("claude-code", "claude", "1.9.9 (Claude Code)"),
        ("opencode", "opencode", "2.0.0"),
        ("opencode", "opencode", "0.9.0"),
    ],
)
def test_unknown_major_version_is_incompatible(
    adapter_id: str, name: str, line: str, rig: Rig
) -> None:
    install_fake(rig.bin_dir, name, line)
    adapter = _adapter(rig, adapter_id)
    detection = adapter.detect(rig.context)
    assert detection.state is DetectionState.INCOMPATIBLE
    assert detection.reason == "unsupported_version"
    with pytest.raises(AdapterRefusal):
        adapter.plan(rig.context)


@pytest.mark.parametrize(
    ("adapter_id", "name"), [("claude-code", "claude"), ("opencode", "opencode")]
)
def test_a_binary_that_is_not_the_harness_is_unavailable(
    adapter_id: str, name: str, rig: Rig
) -> None:
    install_fake(rig.bin_dir, name, "hello from something else")
    detection = _adapter(rig, adapter_id).detect(rig.context)
    assert detection.state is DetectionState.UNAVAILABLE
    assert detection.reason == "unexpected_output"


def test_a_failing_probe_is_unavailable(rig: Rig) -> None:
    install_fake(rig.bin_dir, "claude", CLAUDE_VERSION_LINE, exit_code=3)
    detection = ClaudeCodeAdapter(cli_runner=rig.cli).detect(rig.context)
    assert detection.state is DetectionState.UNAVAILABLE
    assert detection.reason == "probe_failed"


def test_a_cmd_launcher_is_never_given_the_credential(rig: Rig) -> None:
    adapter = ClaudeCodeAdapter()  # the real runner: the fake `claude` is a .cmd on Windows
    import sys

    if sys.platform != "win32":
        pytest.skip("batch launchers only exist on Windows")
    with pytest.raises(AdapterRefusal) as refused:
        adapter.write_user_entry(rig.context, adapter.build_entry(MCP_URL, TOKEN))
    assert refused.value.reason == "unsupported_launcher"
    assert TOKEN not in str(refused.value)


def test_the_two_harnesses_are_independent(rig: Rig) -> None:
    _configure(ClaudeCodeAdapter(cli_runner=rig.cli), rig)
    assert (
        ClaudeCodeAdapter(cli_runner=rig.cli).detect(rig.context).state is DetectionState.CONFIGURED
    )
    assert OpenCodeAdapter().detect(rig.context).state is DetectionState.CONFIGURATION_MISSING
