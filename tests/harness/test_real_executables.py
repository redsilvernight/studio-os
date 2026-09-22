from __future__ import annotations

import os
from pathlib import Path

import pytest
from studio_client.harness.base import DetectionState, HarnessAdapter, HarnessContext
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.probe import locate_executable

MCP_URL = "https://studio.example/mcp"


def _real(adapter: HarnessAdapter) -> bool:
    return (
        locate_executable(adapter.executable_names, path_env=os.environ.get("PATH", "")) is not None
    )


@pytest.mark.parametrize(
    "adapter", [ClaudeCodeAdapter(), OpenCodeAdapter()], ids=["claude", "opencode"]
)
def test_the_real_executable_is_probed_without_touching_any_configuration(
    adapter: HarnessAdapter, tmp_path: Path
) -> None:
    if not _real(adapter):
        pytest.skip(f"{adapter.adapter_id} is not installed on this machine")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = HarnessContext(
        workspace_root=workspace,
        mcp_url=MCP_URL,
        env=dict(os.environ),
        probe_cwd=tmp_path,
    )
    detection = adapter.detect(context)
    assert detection.state in {
        DetectionState.CONFIGURATION_MISSING,
        DetectionState.INCOMPATIBLE,
    }, detection
    if detection.state is DetectionState.CONFIGURATION_MISSING:
        assert detection.version
    assert list(workspace.iterdir()) == [], "detection never writes"
