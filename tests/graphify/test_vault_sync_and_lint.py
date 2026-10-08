"""Tests for Phase 5: the ADR -> vault sync, and the DEC integrity linter in
its two modes -- the default one (repo docs/decisions/DEC-*.md vs the server
snapshot docs/DEC_EXPORT.json) and the legacy local-vault mode reached only
through an explicit `--vault <dir>`. All synthetic fixtures under tmp_path --
never the real project's docs/decisions/, its snapshot, or a real vault."""

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
from scripts.vault_lint import (
    SNAPSHOT_MODE,
    VAULT_MODE,
    run_lint,
    run_snapshot_lint,
    run_vault_lint,
)
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


def _snapshot_decision(
    dec_id: str, title: str = "Titre", status: str = "accepted", **extra: Any
) -> dict[str, Any]:
    return {
        "readable_id": dec_id,
        "title": title,
        "status": status,
        "date": "2026-09-13",
        "task_id": None,
        "supersedes": [],
        "superseded_by": [],
        "body": "Corps.",
        "body_source": "markdown",
        **extra,
    }


def _write_snapshot(
    root: Path,
    decisions: list[dict[str, Any]],
    *,
    export_format: str = "studio-dec-export/1",
    filename: str = "DEC_EXPORT.json",
) -> Path:
    path = root / "docs" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"format": export_format, "project_id": "studio-os", "decisions": decisions},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
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


# --- lint: mode par defaut (docs/decisions/DEC-*.md vs snapshot serveur) ------


def test_lint_defaults_to_the_snapshot_and_only_lints_a_vault_when_asked(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_snapshot(root, [_snapshot_decision("DEC-0001")])

    assert run_lint(root).mode == SNAPSHOT_MODE
    assert run_lint(root).errors == []
    assert run_lint(root, tmp_path / "vault").mode == VAULT_MODE


def test_snapshot_lint_flags_coverage_gaps_in_both_directions(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions_dir = root / "docs" / "decisions"
    _write_adr(decisions_dir, "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_adr(decisions_dir, "DEC-0002", "Autre", "Corps.", status="accepted")
    _write_snapshot(root, [_snapshot_decision("DEC-0001"), _snapshot_decision("DEC-0099")])

    report = run_snapshot_lint(root)
    flagged = {(i.check, i.dec_id) for i in report.errors}
    assert ("coverage_docs_to_snapshot", "DEC-0002") in flagged
    assert ("coverage_snapshot_to_docs", "DEC-0099") in flagged
    assert report.adr_count == 2 and report.snapshot_count == 2


def test_snapshot_lint_flags_unexpected_markdown_besides_adrs(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions_dir = root / "docs" / "decisions"
    _write_adr(decisions_dir, "DEC-0001", "Titre", "Corps.", status="accepted")
    (decisions_dir / "_preamble.md").write_text("# support\n", encoding="utf-8")
    (decisions_dir / "DU0-A-inscription-publique.md").write_text("# hors ADR\n", encoding="utf-8")
    _write_snapshot(root, [_snapshot_decision("DEC-0001")])

    report = run_snapshot_lint(root)
    assert [(i.check, i.dec_id) for i in report.errors] == [("unexpected_decisions_file", None)]
    assert "DU0-A-inscription-publique.md" in report.errors[0].message


def test_snapshot_lint_flags_a_foreign_export_format(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_snapshot(root, [_snapshot_decision("DEC-0001")], export_format="studio-dec-export/2")

    report = run_snapshot_lint(root)
    assert [i.check for i in report.errors] == ["snapshot_format"]
    assert "studio-dec-export/2" in report.errors[0].message
    assert report.errors[0].dec_id is None


def test_snapshot_lint_flags_duplicate_readable_id(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_snapshot(root, [_snapshot_decision("DEC-0001"), _snapshot_decision("DEC-0001")])

    report = run_snapshot_lint(root)
    assert [(i.check, i.dec_id) for i in report.errors] == [("duplicate_readable_id", "DEC-0001")]
    assert report.snapshot_count == 1


def test_snapshot_lint_flags_entries_missing_contract_fields(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_snapshot(
        root,
        [
            {"readable_id": "DEC-0001", "title": "Titre", "status": "accepted"},
            {"readable_id": "DEC-0002", "title": "Autre", "status": "accepted"},
        ],
    )

    report = run_snapshot_lint(root)
    assert [i.check for i in report.errors[:2]] == ["snapshot_schema", "snapshot_schema"]
    assert "date" in report.errors[0].message
    assert "supersedes" in report.errors[0].message
    assert report.errors[1].dec_id == "DEC-0002"


def test_snapshot_lint_flags_a_snapshot_that_is_not_a_dec_export(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="accepted")
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "DEC_EXPORT.json").write_text("[]", encoding="utf-8")

    report = run_snapshot_lint(root)
    assert [i.check for i in report.errors] == ["snapshot_unreadable"]


def test_snapshot_lint_flags_a_missing_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="accepted")

    report = run_snapshot_lint(root)
    assert [i.check for i in report.errors] == ["snapshot_unreadable"]


def test_snapshot_lint_flags_dangling_supersedes_reference(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions_dir = root / "docs" / "decisions"
    _write_adr(decisions_dir, "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_snapshot(root, [_snapshot_decision("DEC-0001", supersedes=["DEC-9999"])])

    report = run_snapshot_lint(root)
    assert [(i.check, i.dec_id) for i in report.errors] == [("supersedes_dangling", "DEC-0001")]
    assert "DEC-9999" in report.errors[0].message


def test_snapshot_lint_flags_asymmetric_supersedes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions_dir = root / "docs" / "decisions"
    _write_adr(decisions_dir, "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_adr(decisions_dir, "DEC-0002", "Autre", "Corps.", status="superseded")
    _write_snapshot(
        root,
        [
            _snapshot_decision("DEC-0001", supersedes=["DEC-0002"]),
            _snapshot_decision("DEC-0002", title="Autre", status="superseded"),
        ],
    )

    report = run_snapshot_lint(root)
    assert [(i.check, i.dec_id) for i in report.errors] == [("supersedes_asymmetric", "DEC-0001")]


def test_snapshot_lint_accepts_a_symmetric_supersedes_pair(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions_dir = root / "docs" / "decisions"
    _write_adr(decisions_dir, "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_adr(decisions_dir, "DEC-0002", "Autre", "Corps.", status="superseded")
    _write_snapshot(
        root,
        [
            _snapshot_decision("DEC-0001", supersedes=["DEC-0002"]),
            _snapshot_decision(
                "DEC-0002", title="Autre", status="superseded", superseded_by=["DEC-0001"]
            ),
        ],
    )

    report = run_snapshot_lint(root)
    assert report.errors == []


def test_snapshot_lint_flags_frontmatter_title_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre local", "Corps.", status="accepted")
    _write_snapshot(root, [_snapshot_decision("DEC-0001", title="Titre serveur")])

    report = run_snapshot_lint(root)
    assert [(i.check, i.dec_id) for i in report.errors] == [("title_mismatch", "DEC-0001")]
    assert "Titre serveur" in report.errors[0].message


def test_snapshot_lint_flags_frontmatter_status_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="superseded")
    _write_snapshot(root, [_snapshot_decision("DEC-0001", status="accepted")])

    report = run_snapshot_lint(root)
    assert [(i.check, i.dec_id) for i in report.errors] == [("status_mismatch", "DEC-0001")]
    assert "superseded" in report.errors[0].message


def test_snapshot_lint_reports_zero_errors_on_a_conforming_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions_dir = root / "docs" / "decisions"
    _write_adr(decisions_dir, "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_adr(decisions_dir, "DEC-0002", "Autre", "Corps.", status="proposed")
    (decisions_dir / "_preamble.md").write_text("# support\n", encoding="utf-8")
    _write_snapshot(
        root,
        [
            _snapshot_decision("DEC-0001", supersedes=["DEC-0002"]),
            _snapshot_decision(
                "DEC-0002", title="Autre", status="proposed", superseded_by=["DEC-0001"]
            ),
        ],
    )

    report = run_snapshot_lint(root)
    assert report.errors == []
    assert report.issues == []
    assert report.snapshot_format == "studio-dec-export/1"
    assert "2 ADR(s)" in report.summary() and "2 decision(s)" in report.summary()


def test_snapshot_lint_reports_zero_errors_when_there_is_nothing_to_lint(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "docs" / "decisions").mkdir(parents=True)
    _write_snapshot(root, [])

    report = run_snapshot_lint(root)
    assert report.errors == []


def test_snapshot_lint_rejects_a_dec_file_without_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions_dir = root / "docs" / "decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "DEC-0001-titre.md").write_text("# pas d'ADR\n", encoding="utf-8")
    _write_snapshot(root, [_snapshot_decision("DEC-0001")])

    report = run_snapshot_lint(root)
    checks = sorted({i.check for i in report.errors})
    assert checks == ["coverage_snapshot_to_docs", "malformed_adr"]


def test_snapshot_lint_flags_duplicate_dec_id_across_adr_files(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions_dir = root / "docs" / "decisions"
    _write_adr(decisions_dir, "DEC-0001", "Titre", "Corps.", status="accepted")
    (decisions_dir / "DEC-0001-doublon.md").write_text(
        render_adr_markdown({"id": "DEC-0001", "title": "Titre", "status": "accepted"}, "Corps.\n"),
        encoding="utf-8",
    )
    _write_snapshot(root, [_snapshot_decision("DEC-0001")])

    report = run_snapshot_lint(root)
    assert [(i.check, i.dec_id) for i in report.errors] == [("duplicate_dec_id", "DEC-0001")]
    assert report.adr_count == 1


# --- lint: CLI ---------------------------------------------------------------


def _run_cli(monkeypatch: Any, capsys: Any, *argv: str) -> tuple[int, str]:
    from scripts import vault_lint

    monkeypatch.setattr("sys.argv", ["vault_lint", *argv])
    exit_code = vault_lint.main()
    return exit_code, capsys.readouterr().out


def test_cli_defaults_to_the_snapshot_and_exits_1_with_the_error_list(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_snapshot(root, [_snapshot_decision("DEC-0001", status="proposed")])

    exit_code, out = _run_cli(monkeypatch, capsys, "--root", str(root), "--no-preflight")
    assert exit_code == 1
    assert "[ERROR] status_mismatch (DEC-0001)" in out
    assert "SKIPPED" in out


def test_cli_prints_a_one_line_summary_when_the_snapshot_matches(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_snapshot(root, [_snapshot_decision("DEC-0001")])

    exit_code, out = _run_cli(monkeypatch, capsys, "--root", str(root), "--no-preflight")
    assert exit_code == 0
    assert "studio-dec-export/1" in out
    assert "0 erreur(s), 0 avertissement(s)" in out


def test_cli_accepts_a_snapshot_outside_the_default_location(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.", status="accepted")
    _write_snapshot(root, [_snapshot_decision("DEC-0001")], filename="export/dec.json")

    exit_code, out = _run_cli(
        monkeypatch,
        capsys,
        "--root",
        str(root),
        "--snapshot",
        "docs/export/dec.json",
        "--no-preflight",
    )
    assert exit_code == 0
    assert "conforme" in out


# --- lint: mode vault local (accessible seulement via --vault <dir>) ---------


def test_lint_flags_duplicate_alias(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    _write_vault_note(vault_dir, "a.md", {"aliases": ["DEC-0001"], "dedupe_key": "x"})
    _write_vault_note(vault_dir, "b.md", {"aliases": ["DEC-0001"], "dedupe_key": "y"})

    report = run_vault_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    checks = {i.check for i in report.issues}
    assert "alias_uniqueness" in checks


def test_lint_flags_missing_vault_coverage(tmp_path: Path) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    report = run_vault_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    assert any(i.check == "coverage_repo_to_vault" for i in report.issues)


def test_lint_flags_dangling_alias_with_no_adr(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "docs" / "decisions").mkdir(parents=True)
    vault_dir = tmp_path / "vault"
    _write_vault_note(vault_dir, "a.md", {"aliases": ["DEC-0099"], "dedupe_key": "x"})
    report = run_vault_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
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
    report = run_vault_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
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
    report = run_vault_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
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
    report = run_vault_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
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

    report = run_vault_lint(root, vault_dir, graph_path=graph_path)
    assert report.entities_total == 2
    assert report.entities_resolved == 1
    assert any(i.check == "entity_not_in_graph" for i in report.issues)


def test_lint_reports_zero_errors_on_a_clean_pair(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    vault_dir = tmp_path / "vault"
    _write_vault_note(vault_dir, "a.md", {"aliases": ["DEC-0001"], "dedupe_key": "x"})
    report = run_vault_lint(root, vault_dir, graph_path=tmp_path / "nope.json")
    assert report.errors == []


def test_cli_lints_the_local_vault_only_when_explicitly_given(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    root = tmp_path / "project"
    vault_dir = tmp_path / "vault"
    _write_adr(root / "docs" / "decisions", "DEC-0001", "Titre", "Corps.")
    _write_snapshot(root, [_snapshot_decision("DEC-0001")])
    _write_vault_note(vault_dir, "a.md", {"aliases": ["DEC-0001"], "dedupe_key": "x"})

    exit_code, out = _run_cli(
        monkeypatch,
        capsys,
        "--root",
        str(root),
        "--vault",
        str(vault_dir),
        "--graph-path",
        str(tmp_path / "nope.json"),
        "--no-preflight",
    )
    assert exit_code == 0
    assert "vault notes: 1" in out
