"""P51a detection: a locally edited generated file is a publishable divergence.

The plan carries the managed base and the local content, and reading it never
writes the file it reports.
"""

from __future__ import annotations

from pathlib import Path

from studio_client import bootstrap
from studio_client.bootstrap import (
    load_manifest,
    make_manifest,
    observe,
    plan_divergences,
    plan_files,
    write_manifest,
)
from studio_client.canonical import AGENTS_BEGIN_MARKER
from studio_client.drift import divergence_state, hash_text

from tests.library_bundle import make_agent, sample_bundle

AGENT_PATH = ".claude/agents/studio-tester.md"


def _synced_repo(tmp_path: Path) -> Path:
    write_manifest(tmp_path, make_manifest("demo", "Demo", ["claude-code"]))
    bootstrap.sync(tmp_path, load_manifest(tmp_path), sample_bundle(), confirm=True)
    return tmp_path


def _planned(repo: Path, bundle=None):  # noqa: ANN001, ANN202
    return plan_files(repo, load_manifest(repo), bundle or sample_bundle())


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

    plan = plan_divergences(repo, load_manifest(repo), planned=_planned(repo))

    assert plan.paths == (AGENT_PATH,)
    entry = plan.files[0]
    assert entry.state == "divergent"
    assert entry.kind == "agent"
    assert entry.base == base
    assert entry.local == edited
    assert _snapshot(repo) == before


def test_up_to_date_projections_are_not_divergent(tmp_path: Path) -> None:
    repo = _synced_repo(tmp_path)

    plan = plan_divergences(repo, load_manifest(repo), planned=_planned(repo))

    assert not plan
    assert plan.files == ()


def test_file_still_matching_its_managed_hash_is_outdated_not_divergent(tmp_path: Path) -> None:
    repo = _synced_repo(tmp_path)
    target = repo / AGENT_PATH
    generated = target.read_text(encoding="utf-8")
    changed = sample_bundle()
    agents = dict(changed.agents)
    agents["studio-tester"] = make_agent("studio-tester", instructions="Canonical change.\n")
    changed = type(changed)(
        agents=agents,
        rules=changed.rules,
        skills=changed.skills,
        skill_files=changed.skill_files,
        protocol=changed.protocol,
    )

    plan = plan_divergences(
        repo,
        load_manifest(repo),
        planned=_planned(repo, changed),
        managed_hashes={AGENT_PATH: hash_text(generated)},
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
    planned = _planned(repo)
    report = observe(repo, manifest, planned=planned)
    assert any(item.path == "AGENTS.md" and item.state == "modified" for item in report.files)

    plan = plan_divergences(repo, manifest, planned=planned)

    assert not plan


def test_divergence_state_maps_only_local_modifications() -> None:
    assert divergence_state("locally_modified") == "divergent"
    assert divergence_state("current") is None
    assert divergence_state("outdated") is None
    assert divergence_state("missing") is None
