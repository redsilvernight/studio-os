"""P00 baseline — numérotation des DEC (fichiers vs serveur).

Vérifie le script `scripts/dec_baseline.py` sur des dossiers fixture : comptage
des ADR, trous, doublons, discordances, écart global et portée projet, et le
mode `--check` reproductible. Aucun accès serveur : le snapshot est un fichier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.dec_baseline import (
    REPORT_RELPATH,
    SNAPSHOT_FORMAT,
    build_report,
    load_file_decisions,
    main,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[2]

PROJECT = "2a836038-153c-41cf-879a-73bd794760b0"
OTHER = "fc05e6bd-f646-421c-bb90-37b18330ee1a"


def _write_adr(directory: Path, filename: str, front: dict[str, str], body: str = "Corps.") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    lines.extend(f"{key}: {value}" for key, value in front.items())
    lines.append("---")
    lines.append("")
    lines.append(body)
    (directory / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _snapshot(decisions: list[dict[str, str]]) -> str:
    return json.dumps(
        {
            "format": SNAPSHOT_FORMAT,
            "source": "test",
            "project_scope_id": PROJECT,
            "decisions": decisions,
        },
        indent=2,
        ensure_ascii=False,
    )


def _fixture_root(tmp_path: Path) -> Path:
    decisions = tmp_path / "docs" / "decisions"
    _write_adr(decisions, "DEC-0001-a.md", {"id": "DEC-0001"}, "Un.")
    _write_adr(decisions, "DEC-0003-c.md", {"id": "DEC-0003"}, "Trois.")
    _write_adr(decisions, "NOTE-A.md", {"server_readable_id": "DEC-0004"}, "Note.")
    snapshot = [
        {"readable_id": "DEC-0001", "project_id": PROJECT, "title": "Un", "status": "accepted"},
        {"readable_id": "DEC-0002", "project_id": PROJECT, "title": "Deux", "status": "accepted"},
        {"readable_id": "DEC-0004", "project_id": OTHER, "title": "Quatre", "status": "accepted"},
        {"readable_id": "DEC-0005", "project_id": PROJECT, "title": "Cinq", "status": "accepted"},
    ]
    (tmp_path / "docs" / "DEC_BASELINE_P00.json").write_text(
        _snapshot(snapshot) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_file_inventory_counts_gaps_duplicates_and_mismatch(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions"
    _write_adr(decisions, "DEC-0001-a.md", {"id": "DEC-0001"})
    _write_adr(decisions, "DEC-0002-a.md", {"id": "DEC-0002"})
    _write_adr(decisions, "DEC-0002-b.md", {"id": "DEC-0002"})
    _write_adr(decisions, "DEC-0005-x.md", {"id": "DEC-0009"})
    _write_adr(decisions, "NOTE-B.md", {"title": "sans identifiant DEC"})

    by_id, unmapped, mismatch = load_file_decisions(decisions)

    assert sorted(by_id) == ["DEC-0001", "DEC-0002", "DEC-0009"]
    assert by_id["DEC-0002"] == ["DEC-0002-a.md", "DEC-0002-b.md"]
    assert unmapped == ["NOTE-B.md"]
    assert mismatch == {"DEC-0005-x.md": "DEC-0009"}


def test_build_report_delta_global_and_project(tmp_path: Path) -> None:
    report = build_report(_fixture_root(tmp_path))

    assert report["files"]["adr_files"] == 3
    assert report["files"]["dec_named"] == 2
    assert report["files"]["dec_ids"] == 3
    assert report["files"]["gaps"] == ["DEC-0002"]
    assert report["files"]["duplicates"] == {}
    assert report["files"]["renamed"] == [["DEC-0004", "NOTE-A.md"]]

    assert report["server"]["all"]["count"] == 4
    assert report["server"]["all"]["gaps"] == ["DEC-0003"]
    assert report["server"]["project"]["count"] == 3
    assert report["server"]["out_of_scope"] == {"count": 1, "ids": ["DEC-0004"]}

    assert report["delta"]["global"]["file_only"] == ["DEC-0003"]
    assert report["delta"]["global"]["server_only"] == ["DEC-0002", "DEC-0005"]
    assert report["delta"]["project"]["file_only"] == ["DEC-0003", "DEC-0004"]
    assert report["delta"]["project"]["server_only"] == ["DEC-0002", "DEC-0005"]


def test_markdown_render_is_deterministic(tmp_path: Path) -> None:
    report = build_report(_fixture_root(tmp_path))
    assert render_markdown(report) == render_markdown(report)
    assert "Présents au serveur seulement" in render_markdown(report)


def test_check_mode_is_stale_then_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _fixture_root(tmp_path)
    monkeypatch.setattr("sys.argv", ["dec_baseline", "--root", str(root), "--apply"])
    assert main() == 0
    assert (root / REPORT_RELPATH).is_file()

    monkeypatch.setattr("sys.argv", ["dec_baseline", "--root", str(root), "--check"])
    assert main() == 0

    _write_adr(root / "docs" / "decisions", "DEC-0006-f.md", {"id": "DEC-0006"})
    assert main() == 1


def test_committed_baseline_matches_repository() -> None:
    report = build_report(ROOT)

    snapshot = json.loads((ROOT / "docs" / "DEC_BASELINE_P00.json").read_text(encoding="utf-8"))
    assert snapshot["format"] == SNAPSHOT_FORMAT
    assert report["snapshot"]["entries"] == len(snapshot["decisions"])

    committed = (ROOT / REPORT_RELPATH).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == render_markdown(report)
