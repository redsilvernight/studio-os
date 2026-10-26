from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from studio_client import machine_setup


@pytest.fixture
def git_path() -> tuple[str, ...]:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("Git executable unavailable")
    return (str(Path(executable).parent),)


def test_mutations_require_confirmation(tmp_path: Path, git_path: tuple[str, ...]) -> None:
    repo = tmp_path / "repo"
    result = machine_setup.init_versioning(repo, branch="main", confirm=False, path_dirs=git_path)
    assert result["state"] == "confirmation_required"
    assert not (repo / ".git").exists()


def test_configure_local_and_global_with_readback(
    tmp_path: Path, git_path: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.gitconfig"))
    local = machine_setup.configure_versioning(
        tmp_path,
        repo,
        scope="local",
        name="Local User",
        email="local@example.test",
        confirm=True,
        path_dirs=git_path,
    )
    global_ = machine_setup.configure_versioning(
        tmp_path,
        None,
        scope="global",
        name="Global User",
        email="global@example.test",
        confirm=True,
        path_dirs=git_path,
    )
    assert local["ok"] and global_["ok"]
    assert local["readback"]["user.name"] == "Local User"
    assert global_["readback"]["user.email"] == "global@example.test"


def test_init_existing_is_idempotent_and_first_commit_possible(
    tmp_path: Path, git_path: tuple[str, ...]
) -> None:
    repo = tmp_path / "repo"
    first = machine_setup.init_versioning(repo, branch="main", confirm=True, path_dirs=git_path)
    second = machine_setup.init_versioning(repo, branch="other", confirm=True, path_dirs=git_path)
    assert first["ok"] and first["state"] == "initialized"
    assert second["ok"] and second["state"] == "existing"
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.test"], check=True
    )
    (repo / "README.md").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True
    )
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
        ).returncode
        == 0
    )


def test_init_nonexistent_descendant_does_not_nest(
    tmp_path: Path, git_path: tuple[str, ...]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    result = machine_setup.init_versioning(
        root / "new" / "child", branch="main", confirm=True, path_dirs=git_path
    )
    assert result["state"] == "existing"
    assert not (root / "new" / "child" / ".git").exists()


def test_invalid_branch_has_no_side_effect(tmp_path: Path, git_path: tuple[str, ...]) -> None:
    target = tmp_path / "target"
    result = machine_setup.init_versioning(
        target, branch="bad branch", confirm=True, path_dirs=git_path
    )
    assert result["state"] == "invalid_branch"
    assert not target.exists()
