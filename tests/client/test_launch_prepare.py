from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from studio_client.bootstrap import make_manifest, write_manifest
from studio_client.daemon.launch_prepare import (
    LaunchPreparer,
    PreparationError,
    PreparationRequest,
    ensure_task_worktree,
    make_bootstrap_configurator,
    run_git,
    task_branch_name,
    task_slug,
    worktree_path,
)
from studio_client.errors import StudioApiError
from studio_client.projection_source import ProjectionBundle

from tests.library_bundle import sample_bundle


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


@pytest.mark.parametrize("branch", ["main", "trunk", "release/candidate"])
def test_default_base_uses_repository_branch_without_requiring_dev(
    tmp_path: Path, branch: str
) -> None:
    repo = _repo(tmp_path, base=branch)
    expected = _git(repo, "rev-parse", "HEAD").strip()
    created = ensure_task_worktree(repo, uuid4(), "neutral", fetch=False)
    assert _git(created.path, "rev-parse", "HEAD").strip() == expected
    assert _git(repo, "branch", "--list", "dev").strip() == ""


def test_default_base_prefers_declared_remote_head_to_current_feature_branch(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path, base="main")
    expected = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "update-ref", "refs/remotes/origin/main", expected)
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    _git(repo, "checkout", "-b", "feature/local")
    (repo / "later.txt").write_text("feature-only", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-m", "feature-only")
    created = ensure_task_worktree(repo, uuid4(), "neutral", fetch=False)
    assert _git(created.path, "rev-parse", "HEAD").strip() == expected
    assert not (created.path / "later.txt").exists()


def test_git_timeout_is_a_preparation_error_without_an_invented_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 30)

    monkeypatch.setattr(subprocess, "run", timed_out)
    with pytest.raises(PreparationError, match="timed out"):
        run_git(["status"], tmp_path)


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


def _request(repo: Path) -> PreparationRequest:
    return PreparationRequest(
        repo_root=repo,
        project_id=uuid4(),
        task_id=uuid4(),
        task_title="Demo",
        harness_id="claude-code",
    )


def test_bootstrap_configurator_skips_a_repo_without_manifest(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    def never(project_id: UUID) -> ProjectionBundle:
        raise AssertionError("no fetch without a manifest")

    assert make_bootstrap_configurator(never)(repo, _request(repo)) == ()


def test_bootstrap_configurator_projects_the_library_bundle(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_manifest(repo, make_manifest("demo", "Demo", ["claude-code"]))
    bundle = sample_bundle()
    request = _request(repo)
    fetched: list[UUID] = []

    def fetch(project_id: UUID) -> ProjectionBundle:
        fetched.append(project_id)
        return bundle

    steps = make_bootstrap_configurator(fetch)(repo, request)
    assert steps == ("bootstrap",)
    assert fetched == [request.project_id]
    assert (repo / ".claude" / "rules" / "testing.md").is_file()


def test_bootstrap_configurator_skips_when_the_library_is_unreachable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_manifest(repo, make_manifest("demo", "Demo", ["claude-code"]))

    def unreachable(project_id: UUID) -> ProjectionBundle:
        raise StudioApiError(503, "unavailable", "unreachable")

    assert make_bootstrap_configurator(unreachable)(repo, _request(repo)) == ()
    assert not (repo / ".claude").exists()
