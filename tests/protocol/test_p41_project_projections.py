"""P41 — project-scope Library updates: pending first, written only on confirmation."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from studio_client import bootstrap
from studio_client.daemon import project_projections as pp
from studio_client.projection_source import bundle_from_repo
from studio_contracts.local.project_projections import ProjectProjectionsStatus

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> pp.RepoTarget:
    bundle = bundle_from_repo(REPO)
    monkeypatch.setattr(pp, "_fetch_bundle", lambda *_: bundle)
    repo = tmp_path / "repo"
    repo.mkdir()
    return pp.RepoTarget(uuid.uuid4(), uuid.uuid4(), repo)


def _tree(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_pending_update_writes_nothing_in_the_repository(
    target: pp.RepoTarget, tmp_path: Path
) -> None:
    data_root = tmp_path / "data"
    assert pp.mark_project_updates_pending(None, None, [target], data_root)  # type: ignore[arg-type]

    assert _tree(target.repo_path) == set()
    status = pp.project_projections_status(data_root)
    assert [update.workspace_id for update in status.updates] == [target.workspace_id]
    assert {file.state for file in status.updates[0].files} == {"absent"}


def test_apply_writes_projections_and_ignores_only_generated_files(
    target: pp.RepoTarget, tmp_path: Path
) -> None:
    data_root = tmp_path / "data"
    settings = target.repo_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"keep": true}\n', encoding="utf-8")
    (target.repo_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    pp.mark_project_updates_pending(None, None, [target], data_root)  # type: ignore[arg-type]

    result = pp.apply_project_update(None, None, [target], data_root, target.workspace_id)  # type: ignore[arg-type]

    assert result.written
    assert settings.read_text(encoding="utf-8") == '{"keep": true}\n'
    ignore = (target.repo_path / ".gitignore").read_text(encoding="utf-8")
    assert ignore.startswith("node_modules/\n" + pp.GITIGNORE_BEGIN)
    listed = {line for line in ignore.splitlines() if line.startswith("/")}
    assert listed == {f"/{path}" for path in result.ignored}
    assert listed
    assert "/AGENTS.md" not in listed
    assert "/CLAUDE.md" not in listed
    assert "/.claude/settings.json" not in listed
    assert pp.project_projections_status(data_root) == ProjectProjectionsStatus()


def test_gitignore_block_is_replaced_in_place_and_surroundings_preserved(tmp_path: Path) -> None:
    planned = [
        bootstrap.PlannedFile(path=".claude/rules/a.md", content="a", kind="rule"),
        bootstrap.PlannedFile(path="CLAUDE.md", content="c", kind="block", block=True),
    ]
    original = f"head\r\n{pp.GITIGNORE_BEGIN}\n/old\n{pp.GITIGNORE_END}\ntail\n"
    (tmp_path / ".gitignore").write_text(original, encoding="utf-8", newline="")

    assert pp.write_gitignore_block(tmp_path, planned) == [".claude/rules/a.md"]
    first = (tmp_path / ".gitignore").read_bytes()
    assert first == (
        f"head\r\n{pp.GITIGNORE_BEGIN}\n/.claude/rules/a.md\n{pp.GITIGNORE_END}\ntail\n".encode()
    )
    pp.write_gitignore_block(tmp_path, planned)
    assert (tmp_path / ".gitignore").read_bytes() == first


def test_apply_rejects_an_unknown_workspace(target: pp.RepoTarget, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        pp.apply_project_update(None, None, [target], tmp_path, uuid.uuid4())  # type: ignore[arg-type]
