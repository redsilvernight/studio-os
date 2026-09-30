"""P3 local bundle generator — init/check/diff/sync (no DB, no server).

Uses temporary repositories seeded from the real `.agents/` sources, so the
canonical parser, the adapters and the managed-block renderer are exercised
exactly as in production. Covers the P3 golden cases: absent before sync,
second run writes nothing, managed modification refused (or confirmed + backed
up under `ask`), CRLF is not drift, the AGENTS.md block preserves user text.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from studio_client import cli
from studio_client.bootstrap import (
    MANIFEST_RELATIVE_PATH,
    load_manifest,
    observe,
    plan_files,
)
from studio_client.canonical import (
    AGENTS_BEGIN_MARKER,
    AGENTS_END_MARKER,
    CLAUDE_BEGIN_MARKER,
    CLAUDE_END_MARKER,
)

REPO = Path(__file__).resolve().parents[2]


def _repo(tmp_path: Path) -> Path:
    shutil.copytree(REPO / ".agents", tmp_path / ".agents")
    return tmp_path


def _init(repo: Path, *extra: str) -> None:
    cli.main(
        [
            "bootstrap",
            "init",
            "--project-slug",
            "demo",
            "--project-name",
            "Demo",
            "--harness",
            "claude-code",
            "--repo-root",
            str(repo),
            *extra,
        ]
    )


def test_init_writes_manifest(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    assert (repo / Path(*MANIFEST_RELATIVE_PATH.split("/"))).is_file()
    manifest = load_manifest(repo)
    assert manifest.project.slug == "demo"
    assert [ref.id for ref in manifest.harnesses] == ["claude-code"]


def test_init_refuses_overwrite_without_flag(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    with pytest.raises(SystemExit) as excinfo:
        _init(repo)
    assert excinfo.value.code == 1
    _init(repo, "--overwrite")


def test_init_rejects_unknown_harness(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(
            [
                "bootstrap",
                "init",
                "--project-slug",
                "demo",
                "--project-name",
                "Demo",
                "--harness",
                "nope",
                "--repo-root",
                str(repo),
            ]
        )
    assert "unknown harness" in capsys.readouterr().err


def test_check_absent_then_sync_is_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _init(repo)

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bootstrap", "check", "--repo-root", str(repo)])
    assert excinfo.value.code == 1

    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    assert "Wrote .claude/agents/studio-tester.md." in capsys.readouterr().out

    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    assert capsys.readouterr().out.strip() == "Already up to date."

    cli.main(["bootstrap", "check", "--repo-root", str(repo)])


def test_managed_modification_is_refused_under_refuse_policy(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])

    target = repo / ".claude" / "agents" / "studio-tester.md"
    edited = target.read_text(encoding="utf-8") + "\nuser edit\n"
    target.write_text(edited, encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    assert excinfo.value.code == 1
    assert target.read_text(encoding="utf-8") == edited


def test_ask_policy_confirms_and_backs_up(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo, "--on-modified", "ask")
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])

    target = repo / ".claude" / "agents" / "studio-tester.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        cli.main(["bootstrap", "sync", "--repo-root", str(repo)])

    cli.main(["bootstrap", "sync", "--repo-root", str(repo), "--yes"])
    assert "user edit" not in target.read_text(encoding="utf-8")
    backups = list((repo / ".studio-os" / "backups" / "bootstrap").rglob("studio-tester.md"))
    assert backups and "user edit" in backups[0].read_text(encoding="utf-8")


def test_agents_md_block_preserves_user_content(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# My project\n\nuser notes\n", encoding="utf-8")
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])

    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "# My project" in text
    assert "user notes" in text
    assert AGENTS_BEGIN_MARKER in text and AGENTS_END_MARKER in text

    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == text


def test_crlf_on_disk_is_not_drift(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])

    target = repo / ".claude" / "rules" / "contracts.md"
    crlf = target.read_text(encoding="utf-8").replace("\n", "\r\n")
    target.write_bytes(crlf.encode("utf-8"))

    cli.main(["bootstrap", "check", "--repo-root", str(repo)])


def test_diff_reports_missing_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    with pytest.raises(SystemExit):
        cli.main(["bootstrap", "diff", "--repo-root", str(repo)])
    out = capsys.readouterr().out
    assert "+++ b/.claude/agents/studio-tester.md" in out


def test_observe_is_read_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    before = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file())
    manifest = load_manifest(repo)
    report = observe(repo, manifest)
    assert report.summary.absent == len(plan_files(repo, manifest))
    after = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file())
    assert before == after


MINE = "# Mine" + chr(10) * 2 + "user rule" + chr(10)


def test_claude_md_block_preserves_user_content_and_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "CLAUDE.md").write_text(MINE, encoding="utf-8")
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])

    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "user rule" in text
    assert CLAUDE_BEGIN_MARKER in text and CLAUDE_END_MARKER in text
    backups = list((repo / ".studio-os" / "backups" / "bootstrap").rglob("CLAUDE.md"))
    assert backups and backups[0].read_text(encoding="utf-8") == MINE

    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == text


def test_unbalanced_claude_md_markers_are_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    broken = f"{CLAUDE_BEGIN_MARKER}" + chr(10) + "half" + chr(10)
    (repo / "CLAUDE.md").write_text(broken, encoding="utf-8")
    _init(repo)
    with pytest.raises(SystemExit):
        cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == broken


def test_rules_sync_backs_up_agents_md(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    cli.main(["rules", "sync", "--repo-root", str(repo), "--overwrite"])
    backups = list((repo / ".studio-os" / "backups" / "bootstrap").rglob("AGENTS.md"))
    assert backups
