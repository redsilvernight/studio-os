from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from studio_client import cli as cli_module
from studio_client.cli import main as cli_main
from studio_client.config import ClientConfig
from studio_client.daemon.launch_prepare import ensure_task_worktree
from studio_client.daemon.worktree_retention import (
    REASON_ACTIVE_SESSION,
    REASON_DIRTY,
    REASON_LOCKED,
    REASON_MAIN_WORKTREE,
    REASON_UNMANAGED,
    REASON_UNPUSHED,
    VERDICT_CANDIDATE,
    VERDICT_EXCLUDED,
    CleanupEntry,
    CleanupPlan,
    RetentionError,
    apply_cleanup,
    plan_cleanup,
)
from studio_client.errors import StudioApiError
from studio_contracts.sessions import SessionStatus, WorkSession


class _FakeApiClient:
    """Only what `cli._active_session_task_ids` uses: no network, no keyring."""

    sessions: list[WorkSession] = []
    fail_with: Exception | None = None

    def __init__(self, config: Any, token_store: Any = None, **kwargs: Any) -> None:
        self.config = config

    async def __aenter__(self) -> _FakeApiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def list_sessions(self, *, task_id: UUID | None = None) -> list[WorkSession]:
        if _FakeApiClient.fail_with is not None:
            raise _FakeApiClient.fail_with
        return list(_FakeApiClient.sessions)


def _install_api(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sessions: list[WorkSession],
    configured: bool = True,
    fail_with: Exception | None = None,
) -> None:
    _FakeApiClient.sessions = sessions
    _FakeApiClient.fail_with = fail_with
    monkeypatch.setattr(cli_module, "StudioApiClient", _FakeApiClient)
    monkeypatch.setattr(
        cli_module,
        "_optional_config",
        lambda: ClientConfig(api_base_url="http://test") if configured else None,
    )


def _session(task_id: UUID, status: SessionStatus = SessionStatus.ACTIVE) -> WorkSession:
    return WorkSession(
        id=uuid4(),
        task_id=task_id,
        machine_id=uuid4(),
        started_at=datetime.now(UTC),
        status=status,
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
    """A repository with a real `origin`, so a worktree can genuinely be pushed."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", remote)
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", base)
    _git(repo, "config", "user.email", "studio@example.test")
    _git(repo, "config", "user.name", "Studio Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", base)
    return repo


def _task_worktree(repo: Path, *, slug: str = "demo") -> tuple[UUID, Path, str]:
    task_id = uuid4()
    worktree = ensure_task_worktree(repo, task_id, slug)
    return task_id, worktree.path, worktree.branch


def _verdict(plan: CleanupPlan, path: Path) -> CleanupEntry:
    match = next((entry for entry in plan.entries if entry.path == path), None)
    assert match is not None, f"{path} is missing from the plan"
    return match


def _refs(repo: Path) -> str:
    return _git(repo, "worktree", "list", "--porcelain") + _git(
        repo, "for-each-ref", "--format=%(refname)", "refs/heads/"
    )


def test_clean_pushed_worktree_is_a_candidate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, path, branch = _task_worktree(repo)
    (path / "feature.txt").write_text("done\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "work")
    _git(path, "push", "-u", "origin", branch)

    plan = plan_cleanup(repo, active_task_ids=())

    entry = _verdict(plan, path)
    assert entry.verdict == VERDICT_CANDIDATE
    assert entry.reasons == ()
    assert entry.branch == branch
    assert plan.candidates == (entry,)


def test_uncommitted_work_is_excluded_as_dirty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, path, _ = _task_worktree(repo)
    (path / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")

    entry = _verdict(plan_cleanup(repo, active_task_ids=()), path)

    assert entry.verdict == VERDICT_EXCLUDED
    assert entry.reasons == (REASON_DIRTY,)


def test_commits_missing_from_the_upstream_are_excluded_as_unpushed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, path, _ = _task_worktree(repo)
    (path / "feature.txt").write_text("done\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "never pushed")

    entry = _verdict(plan_cleanup(repo, active_task_ids=()), path)

    assert entry.reasons == (REASON_UNPUSHED,)


def test_a_task_with_a_live_session_is_excluded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    task_id, path, _ = _task_worktree(repo)

    idle = _verdict(plan_cleanup(repo, active_task_ids=()), path)
    busy = _verdict(plan_cleanup(repo, active_task_ids=[task_id]), path)

    assert idle.reasons == ()
    assert busy.verdict == VERDICT_EXCLUDED
    assert busy.reasons == (REASON_ACTIVE_SESSION,)


def test_a_locked_worktree_is_excluded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, path, _ = _task_worktree(repo)
    _git(repo, "worktree", "lock", str(path))

    entry = _verdict(plan_cleanup(repo, active_task_ids=()), path)

    assert entry.verdict == VERDICT_EXCLUDED
    assert entry.reasons == (REASON_LOCKED,)


def test_the_main_worktree_is_never_a_candidate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, path, _ = _task_worktree(repo)

    plan = plan_cleanup(repo, active_task_ids=())
    main = _verdict(plan, repo)

    assert main.reasons == (REASON_MAIN_WORKTREE,)
    assert main.verdict == VERDICT_EXCLUDED
    assert repo.is_dir()
    assert path.is_dir()
    assert [entry.path for entry in plan.candidates] == [path]


def test_a_worktree_outside_the_convention_is_never_claimed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    _git(repo, "worktree", "add", "-b", "scratch", str(elsewhere), "dev")
    _, path, _ = _task_worktree(repo)

    plan = plan_cleanup(repo, active_task_ids=())
    foreign = _verdict(plan, elsewhere)

    assert foreign.verdict == VERDICT_EXCLUDED
    assert foreign.reasons == (REASON_UNMANAGED,)
    assert foreign.task_id_prefix is None
    assert [entry.path for entry in plan.candidates] == [path]

    result = apply_cleanup(repo, plan, confirm_digest=plan.digest)

    assert elsewhere.is_dir()
    assert foreign.path not in result.removed
    assert "scratch" in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")


def test_planning_is_read_only_and_deterministic(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    task_id, dirty_path, _ = _task_worktree(repo, slug="dirty")
    _, candidate_path, _ = _task_worktree(repo, slug="clean")
    (dirty_path / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")
    (candidate_path / "feature.txt").write_text("done\n", encoding="utf-8")
    _git(candidate_path, "add", ".")
    _git(candidate_path, "commit", "-m", "work")
    _git(
        candidate_path,
        "push",
        "-u",
        "origin",
        _git(candidate_path, "branch", "--show-current").strip(),
    )

    before = _refs(repo)
    plan = plan_cleanup(repo, active_task_ids=[task_id])
    again = plan_cleanup(repo, active_task_ids=[task_id])

    assert _refs(repo) == before
    assert [entry.path for entry in plan.entries] == [
        entry.path for entry in sorted(plan.entries, key=lambda item: str(item.path))
    ]
    assert again.digest == plan.digest
    assert len(plan.digest) == 64
    assert dirty_path.is_dir()


def test_apply_refuses_a_confirmation_that_is_not_the_plan_digest(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, path, branch = _task_worktree(repo)
    plan = plan_cleanup(repo, active_task_ids=())

    with pytest.raises(RetentionError) as excinfo:
        apply_cleanup(repo, plan, confirm_digest="0" * 64)

    assert excinfo.value.reason == "digest_mismatch"
    assert path.is_dir()
    assert branch in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")


def test_apply_refuses_a_plan_made_stale_by_a_later_change(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, path, branch = _task_worktree(repo)
    (path / "feature.txt").write_text("done\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "work")
    _git(path, "push", "-u", "origin", branch)
    plan = plan_cleanup(repo, active_task_ids=())
    (path / "late.txt").write_text("too late\n", encoding="utf-8")

    with pytest.raises(RetentionError) as excinfo:
        apply_cleanup(repo, plan, confirm_digest=plan.digest)

    assert excinfo.value.reason == "plan_stale"
    assert path.is_dir()
    assert branch in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")


def test_apply_removes_only_the_candidates(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    active_id, active_path, active_branch = _task_worktree(repo, slug="active")
    _, dirty_path, dirty_branch = _task_worktree(repo, slug="dirty")
    _, candidate_path, candidate_branch = _task_worktree(repo, slug="clean")
    (dirty_path / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")
    (candidate_path / "feature.txt").write_text("done\n", encoding="utf-8")
    _git(candidate_path, "add", ".")
    _git(candidate_path, "commit", "-m", "work")
    _git(candidate_path, "push", "-u", "origin", candidate_branch)

    plan = plan_cleanup(repo, active_task_ids=[active_id])
    assert {entry.path for entry in plan.candidates} == {candidate_path}

    result = apply_cleanup(repo, plan, confirm_digest=plan.digest)

    assert result.refused == ()
    assert result.removed == (candidate_path,)
    assert result.deleted_branches == (candidate_branch,)
    assert not candidate_path.exists()
    branches = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()
    assert candidate_branch not in branches
    assert active_branch in branches and dirty_branch in branches
    assert active_path.is_dir() and dirty_path.is_dir()
    assert repo.is_dir()


def test_cli_prune_previews_by_default_and_removes_only_on_its_own_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _, candidate_path, candidate_branch = _task_worktree(repo, slug="clean")
    (candidate_path / "feature.txt").write_text("done\n", encoding="utf-8")
    _git(candidate_path, "add", ".")
    _git(candidate_path, "commit", "-m", "work")
    _git(candidate_path, "push", "-u", "origin", candidate_branch)

    cli_main(["worktrees", "prune", "--repo-root", str(repo), "--json"])
    preview = json.loads(capsys.readouterr().out)

    assert preview["applied"] is None
    assert [entry["path"] for entry in preview["candidates"]] == [str(candidate_path)]
    assert any(entry["reasons"] == ["main_worktree"] for entry in preview["excluded"])
    assert candidate_path.is_dir()

    with pytest.raises(SystemExit) as excinfo:
        cli_main(
            [
                "worktrees",
                "prune",
                "--repo-root",
                str(repo),
                "--confirm",
                "0" * 64,
            ]
        )
    assert excinfo.value.code == 1
    assert candidate_path.is_dir()

    cli_main(
        [
            "worktrees",
            "prune",
            "--repo-root",
            str(repo),
            "--confirm",
            preview["digest"],
            "--offline",
        ]
    )

    assert not candidate_path.exists()
    assert (
        candidate_branch
        not in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()
    )


def test_cli_prune_protects_a_session_the_server_still_reports_active(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    live_id, live_path, _ = _task_worktree(repo, slug="live")
    _, candidate_path, candidate_branch = _task_worktree(repo, slug="clean")
    (candidate_path / "feature.txt").write_text("done\n", encoding="utf-8")
    _git(candidate_path, "add", ".")
    _git(candidate_path, "commit", "-m", "work")
    _git(candidate_path, "push", "-u", "origin", candidate_branch)
    _install_api(monkeypatch, sessions=[_session(live_id), _session(uuid4(), SessionStatus.IDLE)])

    cli_main(["worktrees", "prune", "--repo-root", str(repo), "--json"])
    preview = json.loads(capsys.readouterr().out)

    assert preview["sessions_verified"] is True
    assert preview["active_task_ids"] == [str(live_id)]
    assert [
        entry["reasons"] for entry in preview["excluded"] if entry["path"] == str(live_path)
    ] == [[REASON_ACTIVE_SESSION]]
    assert [entry["path"] for entry in preview["candidates"]] == [str(candidate_path)]

    cli_main(["worktrees", "prune", "--repo-root", str(repo), "--confirm", preview["digest"]])

    assert live_path.is_dir()
    assert not candidate_path.exists()
    assert (
        candidate_branch
        not in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()
    )


@pytest.mark.parametrize("configured", [False, True])
def test_cli_prune_confirm_refuses_an_unverified_session_list(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    configured: bool,
) -> None:
    repo = _repo(tmp_path)
    _, path, branch = _task_worktree(repo)
    _install_api(
        monkeypatch,
        sessions=[],
        configured=configured,
        fail_with=StudioApiError(0, None, "unreachable") if configured else None,
    )

    cli_main(["worktrees", "prune", "--repo-root", str(repo), "--json"])
    captured = capsys.readouterr()
    preview = json.loads(captured.out)

    assert preview["sessions_verified"] is False
    assert "sessions actives non vérifiées" in captured.err

    with pytest.raises(SystemExit) as excinfo:
        cli_main(["worktrees", "prune", "--repo-root", str(repo), "--confirm", preview["digest"]])

    assert excinfo.value.code == 1
    assert "--offline" in capsys.readouterr().err
    assert path.is_dir()
    assert branch in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")


def test_cli_prune_confirm_offline_prunes_without_the_api(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    _, path, branch = _task_worktree(repo)
    _install_api(monkeypatch, sessions=[], configured=False)

    cli_main(["worktrees", "prune", "--repo-root", str(repo), "--json", "--offline"])
    preview = json.loads(capsys.readouterr().out)
    assert preview["sessions_verified"] is False

    cli_main(
        [
            "worktrees",
            "prune",
            "--repo-root",
            str(repo),
            "--confirm",
            preview["digest"],
            "--offline",
        ]
    )

    assert not path.exists()
    assert (
        branch not in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()
    )
