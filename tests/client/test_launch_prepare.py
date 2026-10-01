from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from studio_client.daemon.launch_prepare import (
    LaunchPreparer,
    PreparationError,
    PreparationRequest,
    bootstrap_configurator,
    ensure_task_worktree,
    task_branch_name,
    task_slug,
    worktree_path,
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout


def _repo(tmp_path: Path, *, base: str = "dev") -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", base)
    _git(repo, "config", "user.email", "studio@example.test")
    _git(repo, "config", "user.name", "Studio Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


def test_task_slug_is_ascii_bounded_and_safe() -> None:
    assert task_slug("Préparation : worktree de tâche et configuration IA") == (
        "preparation-worktree-de-tache-et-configu"
    )
    assert task_slug("[AIB R3] Daemon — pull") == "aib-r3-daemon-pull"
    assert task_slug("") == "task"
    assert task_slug("!!!") == "task"
    assert task_slug("a" * 100) == "a" * 40


def test_worktree_and_branch_names_follow_the_convention() -> None:
    task_id = UUID("15f820af-5d79-4a6b-bdeb-b05245f380f9")
    repo = Path("/tmp/Studi'os")
    assert worktree_path(repo, task_id) == Path("/tmp/Studi'os-wt-15f820af")
    assert task_branch_name(task_id, "demo") == "task/15f820af-demo"


def test_ensure_creates_then_reuses_the_task_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    task_id = uuid4()

    created = ensure_task_worktree(repo, task_id, "demo")
    assert created.created is True
    assert created.branch == task_branch_name(task_id, "demo")
    assert created.path == worktree_path(repo, task_id)
    assert created.path.is_dir()
    assert (created.path / "README.md").is_file()
    assert _git(created.path, "rev-parse", "--abbrev-ref", "HEAD").strip() == created.branch

    again = ensure_task_worktree(repo, task_id, "demo")
    assert again.created is False
    assert again.path == created.path


def test_ensure_reuses_an_existing_branch_without_a_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    task_id = uuid4()
    branch = task_branch_name(task_id, "demo")
    _git(repo, "branch", branch)

    created = ensure_task_worktree(repo, task_id, "demo")
    assert created.created is True
    assert _git(created.path, "rev-parse", "--abbrev-ref", "HEAD").strip() == branch


def test_ensure_refuses_a_directory_it_does_not_manage(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    task_id = uuid4()
    target = worktree_path(repo, task_id)
    target.mkdir()

    with pytest.raises(PreparationError) as excinfo:
        ensure_task_worktree(repo, task_id, "demo")
    assert excinfo.value.step == "worktree"


def test_ensure_refuses_a_missing_base_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(PreparationError) as excinfo:
        ensure_task_worktree(repo, uuid4(), "demo", base="does-not-exist")
    assert excinfo.value.step == "worktree"


def test_preparer_runs_each_configurator_in_order(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    task_id = uuid4()
    seen: list[Path] = []

    def first(root: Path, request: PreparationRequest) -> list[str]:
        seen.append(root)
        assert request.harness_id == "claude-code"
        return ["skills"]

    def second(root: Path, request: PreparationRequest) -> list[str]:
        seen.append(root)
        return ["harness"]

    preparer = LaunchPreparer(configurators=[first, second])
    result = preparer.prepare(
        PreparationRequest(
            repo_root=repo,
            project_id=uuid4(),
            task_id=task_id,
            task_title="Demo task",
            harness_id="claude-code",
        )
    )
    assert result.worktree.path == worktree_path(repo, task_id)
    assert result.steps == ("skills", "harness")
    assert seen == [result.worktree.path, result.worktree.path]


def test_preparer_maps_a_configurator_failure_to_a_closed_step(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    def failing(root: Path, request: PreparationRequest) -> list[str]:
        raise RuntimeError("boom")

    preparer = LaunchPreparer(configurators=[failing])
    with pytest.raises(PreparationError) as excinfo:
        preparer.prepare(
            PreparationRequest(
                repo_root=repo,
                project_id=uuid4(),
                task_id=uuid4(),
                task_title="Demo",
                harness_id="claude-code",
            )
        )
    assert excinfo.value.step == "ia_config"


def test_bootstrap_configurator_skips_a_repo_without_manifest(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    request = PreparationRequest(
        repo_root=repo,
        project_id=uuid4(),
        task_id=uuid4(),
        task_title="Demo",
        harness_id="claude-code",
    )
    assert bootstrap_configurator(repo, request) == ()
