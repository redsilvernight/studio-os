"""dev preflight against real temporary git repos with a local bare remote (no network)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import dev_preflight as dp


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(bare remote, clone under test, second clone used to advance the remote)."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "dev", str(seed)], check=True)
    commit(seed, "a")
    git(seed, "remote", "add", "origin", str(bare))
    git(seed, "push", "-q", "origin", "dev")
    clone, other = tmp_path / "clone", tmp_path / "other"
    for c in (clone, other):
        subprocess.run(["git", "clone", "-q", str(bare), str(c)], check=True)
    return bare, clone, other


def advance_remote(other: Path, name: str) -> str:
    sha = commit(other, name)
    git(other, "push", "-q", "origin", "dev")
    return sha


def test_aligned(repos):
    _, clone, _ = repos
    r = dp.run_preflight(clone)
    assert (r.status, r.promotable, r.remote_verified, r.left, r.right) == (
        "aligned",
        True,
        True,
        0,
        0,
    )
    assert r.local_sha == r.remote_sha == git(clone, "rev-parse", "HEAD")
    assert r.remote_ref == "origin/dev" and r.fetch == "ok" and r.exit_code == 0


def test_behind_fetches_and_reports_counts_and_target_sha(repos):
    _, clone, other = repos
    advance_remote(other, "b")
    target = advance_remote(other, "c")
    before = git(clone, "rev-parse", "HEAD")
    r = dp.run_preflight(clone)
    assert r.status == "behind" and not r.promotable and r.exit_code == 1
    assert (r.left, r.right) == (0, 2)
    assert target in r.message and "left=0 right=2" in r.message
    # No implicit mutation of the worktree or local branch.
    assert git(clone, "rev-parse", "HEAD") == before
    assert git(clone, "rev-parse", "dev") == before
    assert not (clone / "b").exists() and git(clone, "status", "--porcelain") == ""


def test_ahead(repos):
    _, clone, _ = repos
    commit(clone, "local")
    r = dp.run_preflight(clone)
    assert r.status == "ahead" and not r.promotable and r.exit_code == 1
    assert (r.left, r.right) == (1, 0)


def test_diverged(repos):
    _, clone, other = repos
    commit(clone, "local")
    advance_remote(other, "remote")
    r = dp.run_preflight(clone)
    assert r.status == "diverged" and r.exit_code == 1 and (r.left, r.right) == (1, 1)
    assert "left=1 right=1" in r.message


def test_offline_flag_is_never_promotable_even_when_cache_looks_aligned(repos):
    _, clone, _ = repos
    r = dp.run_preflight(clone, allow_fetch=False)
    assert r.status == "offline" and not r.promotable and not r.remote_verified
    assert r.exit_code == 3 and r.left == 0 and r.right == 0
    assert "NOT promotable" in r.message and r.fetch.startswith("skipped")


def test_offline_env_var(repos, monkeypatch):
    _, clone, _ = repos
    monkeypatch.setenv(dp.OFFLINE_ENV, "1")
    r = dp.run_preflight(clone)
    assert r.status == "offline" and not r.promotable


def test_unreachable_remote_is_offline_not_promotable(repos, tmp_path):
    _, clone, _ = repos
    git(clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    r = dp.run_preflight(clone)
    assert r.status == "offline" and not r.promotable and r.fetch.startswith("failed")
    assert r.remote_sha is not None  # cached ref reported for information


def test_stale_cache_offline_does_not_hide_staleness(repos, tmp_path):
    _, clone, other = repos
    advance_remote(other, "b")
    r = dp.run_preflight(clone, allow_fetch=False)
    # Cache says aligned, but it is unverified: never promotable.
    assert r.status == "offline" and not r.promotable


def test_missing_branch_and_not_a_repo(repos, tmp_path):
    _, clone, _ = repos
    assert dp.run_preflight(clone, branch="nope").status == "error"
    plain = tmp_path / "plain"
    plain.mkdir()
    assert dp.run_preflight(plain).exit_code == 2


def test_cli_json_record(repos, capsys):
    _, clone, other = repos
    advance_remote(other, "b")
    code = dp.main(["--root", str(clone), "--json"])
    rec = json.loads(capsys.readouterr().out)
    assert code == 1 and rec["status"] == "behind" and rec["remote_ref"] == "origin/dev"
    assert rec["remote_sha"] and rec["local_sha"] and rec["head_sha"]
    assert dp.record(dp.run_preflight(clone))["status"] == "behind"


def test_vault_lint_main_is_gated_by_preflight(repos, tmp_path, monkeypatch, capsys):
    pytest.importorskip("yaml")
    from scripts import vault_lint

    _, clone, other = repos
    (clone / "docs" / "decisions").mkdir(parents=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    argv = [
        "vault_lint",
        "--root",
        str(clone),
        "--vault-dir",
        str(vault),
        "--graph-path",
        str(tmp_path / "g.json"),
    ]
    monkeypatch.setattr("sys.argv", argv)
    advance_remote(other, "b")
    assert vault_lint.main() == 1
    assert "dev-preflight [behind]" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", [*argv, "--no-preflight"])
    assert vault_lint.main() == 0
    assert "SKIPPED" in capsys.readouterr().out
