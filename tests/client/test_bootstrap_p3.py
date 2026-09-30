"""P3 local bundle generator — init/check/diff/sync (no DB, no server).

Uses temporary repositories seeded from the real `.agents/` sources, so the
canonical parser, the adapters and the managed-block renderer are exercised
exactly as in production. Covers the P3 golden cases: absent before sync,
second run writes nothing, managed modification refused (or confirmed + backed
up under `ask`), CRLF is not drift, the AGENTS.md block preserves user text,
the unified diff is deterministic, and a sync can be rolled back exactly.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from studio_client import cli
from studio_client.bootstrap import (
    MANIFEST_RELATIVE_PATH,
    diff_text,
    list_backups,
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


def test_diff_is_empty_once_up_to_date(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    capsys.readouterr()

    assert diff_text(repo, load_manifest(repo)) == ""
    cli.main(["bootstrap", "diff", "--repo-root", str(repo)])
    assert capsys.readouterr().out.strip() == "no changes"


def test_diff_modified_file_shows_before_and_after(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])

    target = repo / ".claude" / "rules" / "contracts.md"
    original = target.read_text(encoding="utf-8")
    assert "# Contract Discipline" in original
    edited = original.replace("Contract Discipline", "Contract Discipline EDITED", 1)
    target.write_text(edited, encoding="utf-8")
    capsys.readouterr()

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bootstrap", "diff", "--repo-root", str(repo)])
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "--- a/.claude/rules/contracts.md" in out
    assert "+++ b/.claude/rules/contracts.md" in out
    assert "-# Contract Discipline EDITED" in out
    assert "+# Contract Discipline" in out


def test_diff_block_shows_only_added_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# My project\n\nuser notes\n", encoding="utf-8")
    _init(repo)

    with pytest.raises(SystemExit):
        cli.main(["bootstrap", "diff", "--repo-root", str(repo)])
    out = capsys.readouterr().out
    assert "--- a/AGENTS.md" in out
    assert "+++ b/AGENTS.md" in out
    assert f"+{AGENTS_BEGIN_MARKER}" in out
    assert "-# My project" not in out


def test_diff_json_carries_report_and_diff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    manifest = load_manifest(repo)
    capsys.readouterr()

    with pytest.raises(SystemExit):
        cli.main(["bootstrap", "diff", "--repo-root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["summary"]["absent"] == len(plan_files(repo, manifest))
    assert "+++ b/.claude/agents/studio-tester.md" in payload["diff"]


def test_rollback_removes_created_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    assert list((repo / ".claude").rglob("*.md"))

    cli.main(["bootstrap", "rollback", "--repo-root", str(repo)])

    assert not any(p.is_file() for p in (repo / ".claude").rglob("*"))
    assert not (repo / "AGENTS.md").exists()
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bootstrap", "check", "--repo-root", str(repo)])
    assert excinfo.value.code == 1


def test_rollback_restores_replaced_file_bytes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo, "--on-modified", "ask")
    target = repo / ".claude" / "rules" / "contracts.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "CUSTOM CONTRACT RULE\r\nsecond line\r\n"
    target.write_bytes(original.encode("utf-8"))

    cli.main(["bootstrap", "sync", "--repo-root", str(repo), "--yes"])
    assert target.read_bytes() != original.encode("utf-8")

    cli.main(["bootstrap", "rollback", "--repo-root", str(repo)])
    assert target.read_bytes() == original.encode("utf-8")


def test_rollback_refuses_when_file_changed_since_sync(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])

    target = repo / ".claude" / "agents" / "studio-tester.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nedit\n", encoding="utf-8")
    capsys.readouterr()

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bootstrap", "rollback", "--repo-root", str(repo)])
    assert excinfo.value.code == 1
    assert "refusing to roll back" in capsys.readouterr().err
    assert target.exists()

    cli.main(["bootstrap", "rollback", "--repo-root", str(repo), "--force"])
    assert not target.exists()


def test_rollback_twice_refuses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    cli.main(["bootstrap", "rollback", "--repo-root", str(repo)])
    capsys.readouterr()

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bootstrap", "rollback", "--repo-root", str(repo)])
    assert excinfo.value.code == 1
    assert "already rolled back" in capsys.readouterr().err


def test_rollback_without_backup_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    _init(repo)

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bootstrap", "rollback", "--repo-root", str(repo)])
    assert excinfo.value.code == 1
    assert "no bootstrap backup" in capsys.readouterr().err


def test_rollback_restores_user_agents_md(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    original = "# My project\n\nuser notes\n"
    (repo / "AGENTS.md").write_bytes(original.encode("utf-8"))
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    assert AGENTS_BEGIN_MARKER in (repo / "AGENTS.md").read_text(encoding="utf-8")

    cli.main(["bootstrap", "rollback", "--repo-root", str(repo)])
    assert (repo / "AGENTS.md").read_bytes() == original.encode("utf-8")


def test_idempotent_sync_does_not_add_backup(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])

    assert len(list_backups(repo)) == 1


def test_rollback_list_reports_journal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    _init(repo)
    cli.main(["bootstrap", "sync", "--repo-root", str(repo)])
    capsys.readouterr()

    cli.main(["bootstrap", "rollback", "--repo-root", str(repo), "--list", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["backups"]) == 1
    assert payload["backups"][0]["status"] == "applied"
    assert payload["backups"][0]["entries"] > 0
