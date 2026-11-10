"""P51a detection: a locally edited generated file is a publishable divergence.

The plan carries the managed base and the local content, and reading it never
writes the file it reports.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from studio_client import cli
from studio_client.bootstrap import load_manifest, observe, plan_divergences
from studio_client.canonical import AGENTS_BEGIN_MARKER
from studio_client.drift import divergence_state, hash_text

REPO = Path(__file__).resolve().parents[2]
AGENT_PATH = ".claude/agents/studio-tester.md"


def _synced_repo(tmp_path: Path) -> Path:
    shutil.copytree(REPO / ".agents", tmp_path / ".agents")
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
            str(tmp_path),
        ]
    )
    cli.main(["bootstrap", "sync", "--repo-root", str(tmp_path)])
    return tmp_path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_divergent_file_exposes_base_and_local_without_writing(tmp_path: Path) -> None:
    repo = _synced_repo(tmp_path)
    target = repo / AGENT_PATH
    base = target.read_text(encoding="utf-8")
    edited = base + "\nlocal edit\n"
    target.write_text(edited, encoding="utf-8")
    before = _snapshot(repo)

    plan = plan_divergences(repo, load_manifest(repo))

    assert plan.paths == (AGENT_PATH,)
    entry = plan.files[0]
    assert entry.state == "divergent"
    assert entry.kind == "agent"
    assert entry.base == base
    assert entry.local == edited
    assert _snapshot(repo) == before


def test_up_to_date_projections_are_not_divergent(tmp_path: Path) -> None:
    repo = _synced_repo(tmp_path)

    plan = plan_divergences(repo, load_manifest(repo))

    assert not plan
    assert plan.files == ()


def test_file_still_matching_its_managed_hash_is_outdated_not_divergent(tmp_path: Path) -> None:
    repo = _synced_repo(tmp_path)
    target = repo / AGENT_PATH
    generated = target.read_text(encoding="utf-8")
    definition = repo / ".agents" / "definitions" / "studio-tester.md"
    definition.write_text(
        definition.read_text(encoding="utf-8") + "\ncanonical change\n", encoding="utf-8"
    )

    plan = plan_divergences(
        repo, load_manifest(repo), managed_hashes={AGENT_PATH: hash_text(generated)}
    )

    assert not plan


def test_managed_block_edits_are_not_whole_file_divergences(tmp_path: Path) -> None:
    repo = _synced_repo(tmp_path)
    agents_md = repo / "AGENTS.md"
    text = agents_md.read_text(encoding="utf-8")
    agents_md.write_text(
        text.replace(AGENTS_BEGIN_MARKER, f"{AGENTS_BEGIN_MARKER}\nlocal block edit", 1),
        encoding="utf-8",
    )
    manifest = load_manifest(repo)
    report = observe(repo, manifest)
    assert any(item.path == "AGENTS.md" and item.state == "modified" for item in report.files)

    plan = plan_divergences(repo, manifest)

    assert not plan


def test_divergence_state_maps_only_local_modifications() -> None:
    assert divergence_state("locally_modified") == "divergent"
    assert divergence_state("current") is None
    assert divergence_state("outdated") is None
    assert divergence_state("missing") is None
