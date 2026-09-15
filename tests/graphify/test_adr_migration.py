"""Tests for the Phase 4 DECISIONS.md -> unit ADR migration and the Phase 4
idempotent docs/DECISIONS.md index generator.

Everything here runs against synthetic fixtures under tmp_path -- never the
real project's docs/DECISIONS.md or the real AI-Memory vault -- so these
tests are safe to run repeatedly without touching real data. The actual
one-time migration of the real project is a separate, explicit operation
(see the mandate's final report), not something a test suite should trigger.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.adr_common import (
    build_adr_frontmatter,
    content_hash,
    index_vault_notes_by_dec_id,
    parse_adr_markdown,
    parse_decisions_log,
    render_adr_markdown,
    slugify,
)
from scripts.adr_index import render_index
from scripts.adr_migrate import apply_migration, plan_migration

SAMPLE_LOG = """# Decisions log (bootstrap)

Preambule d'introduction, conserve tel quel.

## DEC-0001 — Layout du depot : monorepo uv (`packages/` + `services/`)

Corps de la decision 1. Deuxieme phrase.

## DEC-0002 — Gestionnaire de dependances Python : `uv`

Corps de la decision 2.
"""


def test_parse_decisions_log_splits_preamble_and_entries() -> None:
    log = parse_decisions_log(SAMPLE_LOG)
    assert (
        log.preamble
        == "# Decisions log (bootstrap)\n\nPreambule d'introduction, conserve tel quel."
    )
    assert [d.id for d in log.decisions] == ["DEC-0001", "DEC-0002"]
    assert log.decisions[0].title == "Layout du depot : monorepo uv (`packages/` + `services/`)"
    assert log.decisions[0].body == "Corps de la decision 1. Deuxieme phrase."


def test_parse_decisions_log_rejects_duplicate_ids() -> None:
    dup = SAMPLE_LOG + "\n## DEC-0001 — Doublon\n\nX\n"
    with pytest.raises(ValueError, match="duplicate"):
        parse_decisions_log(dup)


def test_slugify_is_deterministic_and_bounded() -> None:
    title = "Layout du depot : monorepo uv (`packages/` + `services/`)"
    slug = slugify(title)
    assert slug == slugify(title)  # deterministic
    assert " " not in slug and "`" not in slug
    assert len(slugify("x" * 200)) <= 60


def test_build_adr_frontmatter_omits_unknown_fields_without_vault_match() -> None:
    fields = build_adr_frontmatter(
        dec_id="DEC-0001",
        title="T",
        source="docs/DECISIONS.md",
        sync_hash=content_hash("body"),
        vault_note=None,
    )
    assert "status" not in fields
    assert "date" not in fields
    assert "author" not in fields
    assert fields["id"] == "DEC-0001"
    assert fields["sync_hash"].startswith("sha256:")


def test_render_and_parse_adr_markdown_round_trip() -> None:
    fields = {
        "id": "DEC-0001",
        "title": "Some Title",
        "status": "active",
        "source": "docs/DECISIONS.md",
        "sync_hash": "sha256:abc",
    }
    text = render_adr_markdown(fields, "Body text.\n\nMore.")
    parsed_fields, parsed_body = parse_adr_markdown(text)
    assert parsed_fields == fields
    assert parsed_body == "Body text.\n\nMore."


def _write_vault_note(vault_dir: Path, dec_id: str, *, status: str, superseded_by=None) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / f"{dec_id.lower()}.md").write_text(
        f"""---
aliases:
- {dec_id}
status: {status}
created: 2026-09-12
superseded_by: {superseded_by if superseded_by is not None else "null"}
graphify:
  entities:
  - kind: class
    node_id: some_node
    symbol: Some
---
# body
""",
        encoding="utf-8",
    )


def test_index_vault_notes_by_dec_id_matches_by_alias(tmp_path: Path) -> None:
    _write_vault_note(tmp_path, "DEC-0001", status="active")
    index = index_vault_notes_by_dec_id(tmp_path)
    assert "DEC-0001" in index
    assert index["DEC-0001"].frontmatter["status"] == "active"


def test_build_adr_frontmatter_backfills_from_matching_vault_note(tmp_path: Path) -> None:
    _write_vault_note(tmp_path, "DEC-0001", status="active")
    vault_note = index_vault_notes_by_dec_id(tmp_path)["DEC-0001"]
    fields = build_adr_frontmatter(
        dec_id="DEC-0001",
        title="T",
        source="docs/DECISIONS.md",
        sync_hash="sha256:x",
        vault_note=vault_note,
    )
    assert fields["status"] == "active"
    assert fields["date"] == "2026-09-12"
    assert fields["superseded_by"] is None  # a known "not superseded", not omitted
    assert fields["graphify_entities"][0]["symbol"] == "Some"


def _make_project(tmp_path: Path, log_text: str = SAMPLE_LOG) -> Path:
    root = tmp_path / "project"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "DECISIONS.md").write_text(log_text, encoding="utf-8")
    return root


def test_migration_creates_one_adr_per_decision_and_the_preamble(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    vault_dir = tmp_path / "vault"
    plan = plan_migration(root, vault_dir)
    assert {dec_id for dec_id, _t, _c in plan.to_create} == {"DEC-0001", "DEC-0002"}
    assert plan.already_migrated == []
    assert plan.preamble_to_write is not None

    apply_migration(root, plan)
    adrs = sorted((root / "docs" / "decisions").glob("DEC-*.md"))
    assert len(adrs) == 2
    assert (root / "docs" / "decisions" / "_preamble.md").exists()


def test_migration_never_overwrites_an_already_migrated_adr(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    vault_dir = tmp_path / "vault"
    plan = plan_migration(root, vault_dir)
    apply_migration(root, plan)

    adr_path = next((root / "docs" / "decisions").glob("DEC-0001-*.md"))
    hand_edited = adr_path.read_text(encoding="utf-8") + "\n<!-- hand edit -->\n"
    adr_path.write_text(hand_edited, encoding="utf-8")

    second_plan = plan_migration(root, vault_dir)
    assert second_plan.to_create == []
    assert set(second_plan.already_migrated) == {"DEC-0001", "DEC-0002"}

    apply_migration(root, second_plan)  # no-op
    assert adr_path.read_text(encoding="utf-8") == hand_edited


def test_migration_is_lossless_for_body_text(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    plan = plan_migration(root, tmp_path / "vault")
    apply_migration(root, plan)

    source = parse_decisions_log((root / "docs" / "DECISIONS.md").read_text(encoding="utf-8"))
    for decision in source.decisions:
        adr_path = next((root / "docs" / "decisions").glob(f"{decision.id}-*.md"))
        _fields, body = parse_adr_markdown(adr_path.read_text(encoding="utf-8"))
        assert body == decision.body


def test_index_generation_is_idempotent_and_numerically_sorted(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        SAMPLE_LOG + "\n## DEC-0010 — Dixieme decision\n\nCorps 10.\n",
    )
    plan = plan_migration(root, tmp_path / "vault")
    apply_migration(root, plan)

    decisions_dir = root / "docs" / "decisions"
    first = render_index(decisions_dir)
    second = render_index(decisions_dir)
    assert first == second  # idempotent: no diff on a second render

    ids_in_order = [
        line.split("|")[1].strip() for line in first.splitlines() if line.startswith("| DEC-")
    ]
    assert ids_in_order == ["DEC-0001", "DEC-0002", "DEC-0010"]  # numeric, not lexical, order
