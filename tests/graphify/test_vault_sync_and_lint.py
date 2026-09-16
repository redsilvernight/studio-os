"""Tests for Phase 5: the ADR -> vault sync and the repo/vault integrity
linter. All synthetic fixtures under tmp_path -- never the real project's
docs/decisions/ or the real AI-Memory vault."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from scripts.adr_common import (
    adr_filename,
    content_hash,
    render_adr_markdown,
)
from scripts.vault_lint import run_lint
from scripts.vault_sync import apply_sync, plan_sync


def _write_adr(
    decisions_dir: Path, dec_id: str, title: str, body: str, **extra_fields: Any
) -> Path:
    decisions_dir.mkdir(parents=True, exist_ok=True)
    fields = {
        "id": dec_id,
        "title": title,
        "source": "docs/DECISIONS.md",
        "sync_hash": content_hash(body),
        **extra_fields,
    }
    path = decisions_dir / adr_filename(dec_id, title)
    path.write_text(render_adr_markdown(fields, body), encoding="utf-8")
    return path


def _write_vault_note(
    vault_dir: Path, filename: str, frontmatter: dict[str, Any], body: str = "# body\n"
) -> Path:
    vault_dir.mkdir(parents=True, exist_ok=True)
    text = (
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=True, allow_unicode=True) + "---\n" + body
    )
    path = vault_dir / filename
    path.write_text(text, encoding="utf-8")
    return path


# --- sync ------------------------------------------------------------------


def test_sync_fills_missing_status_on_vault_note(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="active")
    _write_vault_note(
        vault_dir,
        "dec-0001.md",
        {
            "aliases": ["DEC-0001"],
            "dedupe_key": "decision:studio-os:titre",
            "sources": [],
        },
    )

    plan = plan_sync(root, vault_dir)
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.kind == "update"
    assert action.new_frontmatter is not None
    assert action.new_frontmatter["status"] == "active"
    assert action.conflicts == []

    apply_sync(plan)
    reloaded = yaml.safe_load(
        (vault_dir / "dec-0001.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert reloaded["status"] == "active"
    assert reloaded["aliases"] == ["DEC-0001"]  # identity untouched


def test_sync_never_overwrites_a_disagreeing_status_reports_conflict(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="active")
    _write_vault_note(
        vault_dir,
        "dec-0001.md",
        {
            "aliases": ["DEC-0001"],
            "dedupe_key": "decision:studio-os:titre",
            "status": "superseded",  # disagrees with the ADR
        },
    )

    plan = plan_sync(root, vault_dir)
    action = plan.actions[0]
    assert len(action.conflicts) == 1
    assert action.conflicts[0].field == "status"
    assert action.conflicts[0].adr_value == "active"
    assert action.conflicts[0].vault_value == "superseded"

    apply_sync(plan)
    reloaded = yaml.safe_load(
        (vault_dir / "dec-0001.md").read_text(encoding="utf-8").split("---")[1]
    )
    assert reloaded["status"] == "superseded"  # untouched, not silently overwritten


def test_sync_preserves_body_prose_and_only_touches_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="active")
    human_body = "# Titre\n\n## Contexte\n\nTexte humain riche, jamais touche.\n"
    _write_vault_note(
        vault_dir,
        "dec-0001.md",
        {
            "aliases": ["DEC-0001"],
            "dedupe_key": "decision:studio-os:titre",
        },
        body=human_body,
    )

    plan = plan_sync(root, vault_dir)
    apply_sync(plan)
    reloaded_text = (vault_dir / "dec-0001.md").read_text(encoding="utf-8")
    assert human_body.strip() in reloaded_text


def test_sync_is_idempotent_second_run_reports_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="active")
    _write_vault_note(
        vault_dir,
        "dec-0001.md",
        {
            "aliases": ["DEC-0001"],
            "dedupe_key": "decision:studio-os:titre",
        },
    )

    apply_sync(plan_sync(root, vault_dir))
    second = plan_sync(root, vault_dir)
    assert [a.kind for a in second.actions] == ["unchanged"]


def test_sync_merges_graphify_entities_additively(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(
        root / "docs" / "decisions",
        "DEC-0001",
        "Titre",
        "Corps.",
        status="active",
        graphify_entities=[{"node_id": "a", "symbol": "A"}, {"node_id": "b", "symbol": "B"}],
    )
    _write_vault_note(
        vault_dir,
        "dec-0001.md",
        {
            "aliases": ["DEC-0001"],
            "dedupe_key": "decision:studio-os:titre",
            "graphify": {"entities": [{"node_id": "a", "symbol": "A"}]},
        },
    )

    plan = plan_sync(root, vault_dir)
    apply_sync(plan)
    reloaded = yaml.safe_load(
        (vault_dir / "dec-0001.md").read_text(encoding="utf-8").split("---")[1]
    )
    node_ids = {e["node_id"] for e in reloaded["graphify"]["entities"]}
    assert node_ids == {"a", "b"}


def test_sync_creates_a_note_when_none_exists_yet(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(
        root / "docs" / "decisions", "DEC-0001", "Titre", "Corps de la decision.", status="active"
    )

    plan = plan_sync(root, vault_dir)
    action = plan.actions[0]
    assert action.kind == "create"
    assert action.new_frontmatter is not None
    assert action.new_frontmatter["aliases"] == ["DEC-0001"]
    assert action.new_frontmatter["status"] == "active"
    assert "dedupe_key" in action.new_frontmatter
    # no fabricated fields: nothing invents a Contexte/Consequences section
    # or a confidence rating that was never actually established
    assert "confidence" not in action.new_frontmatter
    assert action.new_body is not None
    assert "Corps de la decision." in action.new_body

    apply_sync(plan)
    assert action.vault_path is not None
    assert action.vault_path.exists()

    # idempotent: the freshly created note is now findable by alias, so a
    # second plan sees it as already synced rather than creating a duplicate
    second = plan_sync(root, vault_dir)
    assert second.actions[0].kind in ("update", "unchanged")


# --- lint --------------------------------------------------------------


def test_lint_flags_duplicate_alias(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    _write_vault_note(vault_dir, "a.md", {"aliases": ["DEC-0001"], "dedupe_key": "x"})
    _write_vault_note(vault_dir, "b.md", {"aliases": ["DEC-0001"], "dedupe_key": "y"})

    report = run_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    checks = {i.check for i in report.issues}
    assert "alias_uniqueness" in checks


def test_lint_flags_missing_vault_coverage(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    report = run_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    assert any(i.check == "coverage_repo_to_vault" for i in report.issues)


def test_lint_flags_dangling_alias_with_no_adr(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "docs" / "decisions").mkdir(parents=True)
    vault_dir = tmp_path / "vault"
    _write_vault_note(vault_dir, "a.md", {"aliases": ["DEC-0099"], "dedupe_key": "x"})
    report = run_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    assert any(i.check == "coverage_vault_to_repo" for i in report.issues)


def test_lint_flags_null_node_id_without_unresolved_flag(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    vault_dir = tmp_path / "vault"
    _write_vault_note(
        vault_dir,
        "a.md",
        {
            "aliases": ["DEC-0001"],
            "dedupe_key": "x",
            "graphify": {"entities": [{"node_id": None, "symbol": "X"}]},
        },
    )
    report = run_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    assert any(i.check == "unjustified_null_entity" for i in report.issues)


def test_lint_allows_null_node_id_when_marked_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    vault_dir = tmp_path / "vault"
    _write_vault_note(
        vault_dir,
        "a.md",
        {
            "aliases": ["DEC-0001"],
            "dedupe_key": "x",
            "graphify": {"entities": [{"node_id": None, "symbol": "X", "unresolved": True}]},
        },
    )
    report = run_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    assert not any(i.check == "unjustified_null_entity" for i in report.issues)


def test_lint_flags_dangling_superseded_by(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    vault_dir = tmp_path / "vault"
    _write_vault_note(
        vault_dir,
        "a.md",
        {
            "aliases": ["DEC-0001"],
            "dedupe_key": "x",
            "superseded_by": "DEC-9999",
        },
    )
    report = run_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    assert any(i.check == "dangling_reference" for i in report.issues)


def test_lint_computes_entity_resolution_against_graph(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    vault_dir = tmp_path / "vault"
    _write_vault_note(
        vault_dir,
        "a.md",
        {
            "aliases": ["DEC-0001"],
            "dedupe_key": "x",
            "graphify": {
                "entities": [
                    {"node_id": "resolved_one", "symbol": "A"},
                    {"node_id": "missing_one", "symbol": "B"},
                ]
            },
        },
    )
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps({"nodes": [{"id": "resolved_one"}]}), encoding="utf-8")

    report = run_lint(root, vault_dir, graph_path=graph_path)
    assert report.entities_total == 2
    assert report.entities_resolved == 1
    assert any(i.check == "entity_not_in_graph" for i in report.issues)


def test_lint_reports_zero_errors_on_a_clean_pair(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    vault_dir = tmp_path / "vault"
    _write_vault_note(vault_dir, "a.md", {"aliases": ["DEC-0001"], "dedupe_key": "x"})
    report = run_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    assert report.errors == []
