from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
from studio_code_graph.graphify.locator import (
    EXECUTABLE_ENV,
    parse_version,
    probe_install,
    resolve_executable,
)
from studio_code_graph.provider import ProbeState


def fake_executable(directory: Path, output: str, exit_code: int = 0) -> Path:
    if sys.platform == "win32":
        path = directory / "fake-graphify.cmd"
        path.write_text(f"@echo off\r\necho {output}\r\nexit /b {exit_code}\r\n", encoding="utf-8")
    else:
        path = directory / "fake-graphify"
        path.write_text(f"#!/bin/sh\necho '{output}'\nexit {exit_code}\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("graphify 0.9.59", (0, 9, 59)),
        ("v1.2.3-beta", (1, 2, 3)),
        ("no version here", None),
        ("", None),
    ],
)
def test_parse_version(text: str, expected: tuple[int, int, int] | None) -> None:
    assert parse_version(text) == expected


@pytest.fixture(autouse=True)
def no_ambient_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EXECUTABLE_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)


def test_not_installed_when_nothing_is_found() -> None:
    probe, install = probe_install()
    assert probe.state is ProbeState.NOT_INSTALLED and install is None


def test_configured_relative_or_missing_path_is_rejected(tmp_path: Path) -> None:
    assert resolve_executable(Path("graphify")) is None
    assert resolve_executable(tmp_path / "absent.exe") is None


def test_compatible_version(tmp_path: Path) -> None:
    probe, install = probe_install(fake_executable(tmp_path, "graphify 0.9.59"))
    assert probe.state is ProbeState.AVAILABLE and probe.version == "0.9.59"
    assert install is not None and install.version == "0.9.59"


@pytest.mark.parametrize("version", ["0.8.9", "1.0.0", "2.3.4"])
def test_incompatible_version(tmp_path: Path, version: str) -> None:
    probe, install = probe_install(fake_executable(tmp_path, f"graphify {version}"))
    assert probe.state is ProbeState.INCOMPATIBLE and probe.version == version
    assert install is None and probe.reason


def test_unparsable_output_is_unavailable(tmp_path: Path) -> None:
    probe, install = probe_install(fake_executable(tmp_path, "hello"))
    assert probe.state is ProbeState.UNAVAILABLE and install is None


def test_failing_executable_is_unavailable(tmp_path: Path) -> None:
    probe, _ = probe_install(fake_executable(tmp_path, "graphify 0.9.59", exit_code=2))
    assert probe.state is ProbeState.UNAVAILABLE


def test_environment_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EXECUTABLE_ENV, str(fake_executable(tmp_path, "graphify 0.9.59")))
    probe, _ = probe_install()
    assert probe.state is ProbeState.AVAILABLE


def test_broken_override_does_not_fall_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = str(fake_executable(tmp_path, "graphify 0.9.59"))
    monkeypatch.setenv(EXECUTABLE_ENV, str(tmp_path / "absent"))
    monkeypatch.setattr("shutil.which", lambda name: found)
    probe, _ = probe_install()
    assert probe.state is ProbeState.NOT_INSTALLED
