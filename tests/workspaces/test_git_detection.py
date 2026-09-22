from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from studio_workspaces.git_detection import GitStatus, detect_git

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")


def _run(*args: str, cwd: Path) -> None:
    subprocess.run([GIT or "git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(cwd: Path) -> None:
    (cwd / "file.txt").write_text("data", encoding="utf-8")
    _run("add", ".", cwd=cwd)
    _run("-c", "user.email=t@t.test", "-c", "user.name=t", "commit", "-m", "init", cwd=cwd)


@needs_git
def test_valid_repo_with_branch(tmp_path: Path) -> None:
    _run("init", "-b", "main", cwd=tmp_path)
    (tmp_path / "file.txt").write_text("data", encoding="utf-8")
    _run("add", ".", cwd=tmp_path)
    _run("-c", "user.email=t@t.test", "-c", "user.name=t", "commit", "-m", "init", cwd=tmp_path)
    info = detect_git(str(tmp_path))
    assert info.status == GitStatus.VALID
    assert info.branch == "main"
    assert not info.detached
    assert info.commit is not None and len(info.commit) == 40
    assert info.remote is None


@needs_git
def test_remote_is_reported(tmp_path: Path) -> None:
    _run("init", "-b", "main", cwd=tmp_path)
    _commit(tmp_path)
    _run("remote", "add", "origin", "https://example.test/demo.git", cwd=tmp_path)
    info = detect_git(str(tmp_path))
    assert info.status == GitStatus.VALID
    assert info.remote == "https://example.test/demo.git"


@needs_git
def test_detached_head(tmp_path: Path) -> None:
    _run("init", "-b", "main", cwd=tmp_path)
    (tmp_path / "file.txt").write_text("data", encoding="utf-8")
    _run("add", ".", cwd=tmp_path)
    _run("-c", "user.email=t@t.test", "-c", "user.name=t", "commit", "-m", "init", cwd=tmp_path)
    sha = subprocess.run(
        [GIT or "git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _run("checkout", sha, cwd=tmp_path)
    info = detect_git(str(tmp_path))
    assert info.status == GitStatus.VALID
    assert info.detached
    assert info.branch is None
    assert info.commit == sha


@needs_git
def test_plain_folder_is_not_a_repo(tmp_path: Path) -> None:
    info = detect_git(str(tmp_path))
    assert info.status == GitStatus.NOT_A_REPO


@needs_git
def test_broken_git_dir_is_invalid(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    info = detect_git(str(tmp_path))
    assert info.status == GitStatus.INVALID_REPO


def test_missing_path_is_inaccessible(tmp_path: Path) -> None:
    info = detect_git(str(tmp_path / "gone"))
    assert info.status == GitStatus.INACCESSIBLE


def test_git_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", "")
    info = detect_git(str(tmp_path))
    assert info.status == GitStatus.GIT_ABSENT


@needs_git
def test_probe_inside_subdirectory_finds_root(tmp_path: Path) -> None:
    _run("init", "-b", "main", cwd=tmp_path)
    _commit(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    info = detect_git(str(nested))
    assert info.status == GitStatus.VALID
    assert info.repo_root is not None
    assert os.path.normcase(info.repo_root) == os.path.normcase(str(tmp_path))


def test_detection_never_writes(tmp_path: Path) -> None:
    before = sorted(p.name for p in tmp_path.iterdir())
    detect_git(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == before
