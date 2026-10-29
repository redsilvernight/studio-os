from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from studio_client.harness import json_mcp
from studio_client.harness.base import AdapterRefusal, DetectionState, HarnessContext
from studio_client.harness.codex import CodexAdapter
from studio_client.harness.probe import ProbeOutput, locate_bundled_codex


def _bundled(local_appdata: Path, build: str, *, stamp: float | None = None) -> Path:
    directory = local_appdata / "OpenAI" / "Codex" / "bin" / build
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / ("codex.exe" if os.name == "nt" else "codex")
    executable.write_bytes(b"MZ")
    if stamp is not None:
        os.utime(executable, (stamp, stamp))
    return executable.resolve()


def _context(
    tmp_path: Path, *, local_appdata: Path | None, workspace: Path | None = None
) -> HarnessContext:
    root = workspace if workspace is not None else tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = {} if local_appdata is None else {"LOCALAPPDATA": str(local_appdata)}
    return HarnessContext(
        workspace_root=root,
        mcp_url="http://127.0.0.1/mcp",
        env=env,
        probe_cwd=root,
        home=home,
    )


def test_the_most_recent_bundled_build_wins(tmp_path: Path) -> None:
    local_appdata = tmp_path / "localappdata"
    _bundled(local_appdata, "593bad775a30e636", stamp=1_700_000_000)
    newest = _bundled(local_appdata, "08d187884f2330d1", stamp=1_700_000_100)
    assert locate_bundled_codex(local_appdata) == newest


def test_a_build_without_the_cli_is_ignored(tmp_path: Path) -> None:
    local_appdata = tmp_path / "localappdata"
    helper = local_appdata / "OpenAI" / "Codex" / "bin" / "593bad775a30e636"
    helper.mkdir(parents=True)
    (helper / "rg.exe").write_bytes(b"MZ")
    assert locate_bundled_codex(local_appdata) is None


def test_an_absent_bundled_tree_is_not_found(tmp_path: Path) -> None:
    assert locate_bundled_codex(tmp_path / "localappdata") is None
    assert locate_bundled_codex(None) is None


def test_a_bundled_cli_inside_the_workspace_is_refused(tmp_path: Path) -> None:
    _bundled(tmp_path, "08d187884f2330d1")
    assert locate_bundled_codex(tmp_path, excluded_dirs=[tmp_path]) is None


def test_the_adapter_falls_back_to_the_bundled_cli(tmp_path: Path) -> None:
    local_appdata = tmp_path / "localappdata"
    bundled = _bundled(local_appdata, "08d187884f2330d1")
    ctx = _context(tmp_path, local_appdata=local_appdata)
    assert CodexAdapter().resolve_executable(ctx) == bundled


def test_the_adapter_refuses_a_bundled_cli_inside_the_workspace(tmp_path: Path) -> None:
    _bundled(tmp_path, "08d187884f2330d1")
    ctx = _context(tmp_path, local_appdata=tmp_path, workspace=tmp_path)
    with pytest.raises(AdapterRefusal) as refusal:
        CodexAdapter().resolve_executable(ctx)
    assert refusal.value.reason == "executable_not_found"


def test_detection_probes_the_bundled_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local_appdata = tmp_path / "localappdata"
    bundled = _bundled(local_appdata, "08d187884f2330d1")
    probed: list[Path] = []

    def fake_probe(
        executable: Path,
        args: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: Path,
    ) -> ProbeOutput:
        probed.append(executable)
        return ProbeOutput(0, "codex-cli 0.165.0")

    monkeypatch.setattr(json_mcp, "run_probe", fake_probe)
    detection = CodexAdapter().detect(_context(tmp_path, local_appdata=local_appdata))
    assert detection.state is DetectionState.CONFIGURATION_MISSING
    assert detection.version == "0.165.0"
    assert probed == [bundled]
