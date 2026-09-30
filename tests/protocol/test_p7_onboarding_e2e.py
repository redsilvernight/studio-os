"""P7 onboarding E2E — blank Godot repository to multi-harness bootstrap.

Automates the reference scenario (AI Bootstrap audit §7, roadmap §9): a blank
Godot repository is seeded with a minimal `.agents/` project source, the local
`bootstrap` generator produces the Claude Code / OpenCode / Codex projections,
and the run is measured. Pure and offline: no database, no server.

Guards the P7 gate:
- the scripted scenario (init -> check -> sync -> add harness -> idempotent);
- OpenCode and Codex added without recreating any `.agents/` source;
- the published metrics are deterministic and match this run byte-for-byte;
- the second-agent task resume is owned by the L4 E2E and the bootstrap is
  harness-neutral, so any harness can pick the task up.
"""

from __future__ import annotations

import json
from pathlib import Path

from studio_client.bootstrap import (
    apply_files,
    load_manifest,
    make_manifest,
    observe,
    plan_files,
    write_manifest,
)
from studio_client.canonical import AGENTS_BEGIN_MARKER, CLAUDE_BEGIN_MARKER
from studio_contracts.bootstrap import BootstrapFileState, OnModified

from scripts.p7_onboarding_metrics import (
    ADDED_HARNESSES,
    BASE_HARNESSES,
    METRICS_FORMAT,
    METRICS_RELATIVE_PATH,
    render_json,
    run_scenario,
    seed_blank_godot,
    seed_minimal_agents,
)

ROOT = Path(__file__).resolve().parents[2]

CONTINUITY_TEST = ROOT / "tests/mcp/test_agent_loop_sync_e2e.py"


def _sync(repo: Path, harnesses: list[str]) -> list[str]:
    manifest = make_manifest("blank-godot", "Blank Godot", harnesses, on_modified=OnModified.REFUSE)
    write_manifest(repo, manifest, overwrite=True)
    planned = plan_files(repo, manifest)
    report = observe(repo, manifest, planned=planned)
    return apply_files(repo, manifest, report, planned=planned, confirm=True)


def test_e2e_blank_godot_to_harnesses(tmp_path: Path) -> None:
    seed_blank_godot(tmp_path)
    seed_minimal_agents(tmp_path)
    assert (tmp_path / "project.godot").is_file()

    assert _sync(tmp_path, BASE_HARNESSES) == [
        ".claude/agents/project-agent.md",
        ".claude/rules/project-conventions.md",
        ".claude/skills/project-workflow/SKILL.md",
        "AGENTS.md",
        "CLAUDE.md",
    ]

    manifest = load_manifest(tmp_path)
    planned = plan_files(tmp_path, manifest)
    report = observe(tmp_path, manifest, planned=planned)
    assert {f.state for f in report.files} == {BootstrapFileState.UP_TO_DATE}

    assert _sync(tmp_path, BASE_HARNESSES) == []


def test_opencode_and_codex_are_added_without_recreating_sources(tmp_path: Path) -> None:
    seed_blank_godot(tmp_path)
    seed_minimal_agents(tmp_path)
    _sync(tmp_path, BASE_HARNESSES)
    sources_before = sorted(
        p.relative_to(tmp_path).as_posix() for p in (tmp_path / ".agents").rglob("*")
    )

    _sync(tmp_path, ADDED_HARNESSES)

    sources_after = sorted(
        p.relative_to(tmp_path).as_posix() for p in (tmp_path / ".agents").rglob("*")
    )
    assert sources_after == sources_before

    canonical = (tmp_path / ".agents" / "skills" / "project-workflow" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for harness in ("opencode", "codex"):
        projected = tmp_path / f".{harness}" / "skills" / "project-workflow" / "SKILL.md"
        assert projected.read_text(encoding="utf-8") == canonical


def test_managed_blocks_point_to_canonical_sources(tmp_path: Path) -> None:
    seed_blank_godot(tmp_path)
    seed_minimal_agents(tmp_path)
    _sync(tmp_path, ADDED_HARNESSES)

    agents_md = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert AGENTS_BEGIN_MARKER in agents_md
    assert "project-conventions" in agents_md
    assert CLAUDE_BEGIN_MARKER in claude_md
    assert ".agents/" in claude_md


def test_scenario_is_deterministic() -> None:
    assert render_json(run_scenario()) == render_json(run_scenario())


def test_published_metrics_match_committed_run() -> None:
    metrics = run_scenario()
    assert metrics["format"] == METRICS_FORMAT
    assert metrics["harness_parity"]["sources_unchanged"] is True
    assert metrics["harness_parity"]["opencode_added_without_source_change"] is True
    assert metrics["harness_parity"]["codex_added_without_source_change"] is True
    assert metrics["sync_output"]["idempotent_second_sync_writes"] == 0
    assert metrics["manual_actions"]["onboarding"]["count"] == 3

    committed = json.loads((ROOT / METRICS_RELATIVE_PATH).read_text(encoding="utf-8"))
    assert committed == metrics


def test_second_agent_resume_is_covered_and_harness_neutral() -> None:
    assert CONTINUITY_TEST.is_file()
    source = CONTINUITY_TEST.read_text(encoding="utf-8")
    assert "studio_start_work" in source
    assert "studio_handoff" in source

    metrics = run_scenario()
    assert metrics["second_agent_resume"]["bootstrap_is_harness_neutral"] is True
