"""The harnesses really installed on this machine, probed against an isolated
home: the suite never reads nor writes the user's own configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from studio_client.harness.backup import BackupStore
from studio_client.harness.base import DetectionState, HarnessAdapter, HarnessContext
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.credentials import CredentialStore
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.probe import locate_executable
from studio_client.harness.registry import HarnessRegistry
from studio_client.harness.service import HarnessService, WorkspaceInfo
from studio_contracts.local.harness import HarnessVerifyRequest, VerifyState

from tests.harness.support import MCP_URL, WORKSPACE_ID, FakeProvisioner


def _real(adapter: HarnessAdapter) -> bool:
    names = adapter.executable_names  # type: ignore[attr-defined]
    return locate_executable(names, path_env=os.environ.get("PATH", "")) is not None


def _env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() != "XDG_CONFIG_HOME"}
    env.pop("STUDIO_MCP_MACHINE_TOKEN", None)
    return env


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return workspace, home


@pytest.mark.parametrize(
    "adapter", [ClaudeCodeAdapter(), OpenCodeAdapter()], ids=["claude", "opencode"]
)
def test_the_real_executable_is_probed_without_touching_any_configuration(
    adapter: HarnessAdapter, tmp_path: Path
) -> None:
    if not _real(adapter):
        pytest.skip(f"{adapter.adapter_id} is not installed on this machine")
    workspace, home = _dirs(tmp_path)
    context = HarnessContext(
        workspace_root=workspace, mcp_url=MCP_URL, env=_env(), probe_cwd=tmp_path, home=home
    )
    detection = adapter.detect(context)
    assert detection.state in {
        DetectionState.CONFIGURATION_MISSING,
        DetectionState.INCOMPATIBLE,
    }, detection
    if detection.state is DetectionState.CONFIGURATION_MISSING:
        assert detection.version
    assert list(workspace.iterdir()) == [], "detection never writes"
    assert list(home.iterdir()) == [], "detection never writes"


@pytest.mark.parametrize(
    "adapter", [ClaudeCodeAdapter(), OpenCodeAdapter()], ids=["claude", "opencode"]
)
def test_verify_returns_unconfigured_when_not_applied(
    adapter: HarnessAdapter, tmp_path: Path
) -> None:
    if not _real(adapter):
        pytest.skip(f"{adapter.adapter_id} is not installed on this machine")
    workspace, home = _dirs(tmp_path)
    env = _env()

    def lookup(workspace_id):
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(workspace_id, workspace, MCP_URL, True)

    def no_probe(url: str, token: str) -> tuple[str | None, int | None]:
        raise AssertionError("an unconfigured harness is never probed")

    service = HarnessService(
        HarnessRegistry([adapter]),
        BackupStore(tmp_path / "backups"),
        lookup,
        credentials=CredentialStore(tmp_path / "credentials.json"),
        provisioner=FakeProvisioner(),
        env=lambda: env,
        home=lambda: home,
        probe_cwd=tmp_path,
        mcp_probe=no_probe,
    )
    result = service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter.adapter_id)
    )
    assert result.state in (VerifyState.UNCONFIGURED, VerifyState.FAILED)
    assert result.adapter_id == adapter.adapter_id
