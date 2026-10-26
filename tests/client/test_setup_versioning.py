from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from studio_client import machine_setup


def test_missing_git_is_explicit_and_changes_nothing(tmp_path: Path) -> None:
    result = machine_setup.probe_versioning(tmp_path, (tmp_path,), ())
    assert result.state == "missing"
    assert result.workspaces == 1
    assert list(tmp_path.iterdir()) == []


def test_git_timeout_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_setup.shutil, "which", lambda *args, **kwargs: "git")

    def timeout(*args: object) -> tuple[int, str]:
        raise subprocess.TimeoutExpired("git", 2)

    monkeypatch.setattr(machine_setup, "_git_check", timeout)
    assert machine_setup.probe_versioning(tmp_path, (), ()).state == "unavailable"


def test_real_git_keeps_local_identity_separate_from_global_and_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("Git executable unavailable")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "absent-global"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    repository = tmp_path / "project"
    repository.mkdir()
    new_project = tmp_path / "new-project"
    new_project.mkdir()

    def git(*args: str) -> None:
        subprocess.run([executable, "-C", str(repository), *args], check=True, capture_output=True)

    git("init")
    git("config", "--local", "user.name", "Test User")
    git("config", "--local", "user.email", "test@example.test")
    git("remote", "add", "origin", "https://example.test/repository.git")
    before = (repository / ".git" / "config").read_bytes()
    result = machine_setup.probe_versioning(
        tmp_path, (repository, new_project), tuple(os.environ.get("PATH", "").split(os.pathsep))
    )
    assert result.state == "checked"
    assert result.identity_configured is False
    assert (result.workspaces, result.repositories, result.with_identity, result.with_remote) == (
        2,
        1,
        1,
        1,
    )
    assert (repository / ".git" / "config").read_bytes() == before
    assert not (new_project / ".git").exists()
    git("remote", "remove", "origin")
    local_only = machine_setup.probe_versioning(
        tmp_path, (repository,), tuple(os.environ.get("PATH", "").split(os.pathsep))
    )
    assert local_only.repositories == local_only.with_identity == 1
    assert local_only.with_remote == 0
