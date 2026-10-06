from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from studio_client.harness import json_mcp
from studio_client.harness.base import AdapterRefusal, DetectionState, HarnessContext
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.probe import ProbeOutput, locate_embedded_claude_code


def _embedded(appdata: Path, version: str) -> Path:
    directory = appdata / "Claude" / "claude-code" / version
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "claude.exe"
    executable.write_bytes(b"MZ")
    return executable.resolve()


def _context(tmp_path: Path, *, appdata: Path, workspace: Path | None = None) -> HarnessContext:
    root = workspace if workspace is not None else tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    return HarnessContext(
        workspace_root=root,
        mcp_url="http://127.0.0.1/mcp",
        env={"APPDATA": str(appdata)},
        probe_cwd=root,
        home=home,
    )


def test_the_highest_embedded_version_wins(tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    _embedded(appdata, "2.1.280")
    newest = _embedded(appdata, "2.1.281")
    assert locate_embedded_claude_code(appdata) == newest


def test_an_absent_embedded_tree_is_not_found(tmp_path: Path) -> None:
    assert locate_embedded_claude_code(tmp_path / "appdata") is None


def test_an_embedded_cli_inside_the_workspace_is_refused(tmp_path: Path) -> None:
    _embedded(tmp_path, "2.1.281")
    assert locate_embedded_claude_code(tmp_path, excluded_dirs=[tmp_path]) is None


def test_the_adapter_falls_back_to_the_embedded_cli(tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    embedded = _embedded(appdata, "2.1.281")
    assert ClaudeCodeAdapter().resolve_executable(_context(tmp_path, appdata=appdata)) == embedded


def test_the_adapter_refuses_an_embedded_cli_inside_the_workspace(tmp_path: Path) -> None:
    _embedded(tmp_path, "2.1.281")
    ctx = _context(tmp_path, appdata=tmp_path, workspace=tmp_path)
    with pytest.raises(AdapterRefusal) as refusal:
        ClaudeCodeAdapter().resolve_executable(ctx)
    assert refusal.value.reason == "executable_not_found"


def test_detection_probes_the_highest_embedded_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    appdata = tmp_path / "appdata"
    _embedded(appdata, "2.1.280")
    newest = _embedded(appdata, "2.1.281")
    probed: list[Path] = []

    def fake_probe(
        executable: Path,
        args: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: Path,
    ) -> ProbeOutput:
        probed.append(executable)
        return ProbeOutput(0, "2.1.281 (Claude Code)")

    monkeypatch.setattr(json_mcp, "run_probe", fake_probe)
    detection = ClaudeCodeAdapter().detect(_context(tmp_path, appdata=appdata))
    assert detection.state is DetectionState.CONFIGURATION_MISSING
    assert detection.version == "2.1.281"
    assert probed == [newest]
