"""The P00 decision-relevance baseline is deterministic and self-consistent."""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from scripts import dec_relevance_eval as dr

ROOT = Path(__file__).resolve().parents[2]


def _load() -> tuple[dict, list]:
    queries = dr.load_queries(ROOT / dr.QUERIES_RELATIVE_PATH)
    corpus = dr.load_corpus(ROOT / dr.CORPUS_RELATIVE_PATH)
    return queries, corpus


def test_labels_are_grounded_in_the_corpus() -> None:
    queries, corpus = _load()
    dr._validate_labels(queries, corpus)
    assert len(queries["queries"]) >= 25
    assert all(query["expected"] for query in queries["queries"])


def test_expected_ids_have_a_decision_file() -> None:
    queries, _ = _load()
    documented = {
        match.group(1)
        for path in (ROOT / "docs" / "decisions").glob("*.md")
        if (match := re.match(r"(DEC-\d{4})", path.name))
    }
    for query in queries["queries"]:
        missing = [
            readable_id for readable_id in query["expected"] if readable_id not in documented
        ]
        assert not missing, f"{query['id']} expects undocumented {missing}"


def test_eval_is_deterministic_and_bounded() -> None:
    queries, corpus = _load()
    selection = queries["selection"]
    kwargs = {"limit": selection["limit"], "max_chars": selection["max_chars"]}

    first = asyncio.run(dr.run_eval(queries, corpus, **kwargs))
    second = asyncio.run(dr.run_eval(queries, corpus, **kwargs))
    assert first == second

    aggregate = first["aggregate"]
    assert 0.0 <= aggregate["micro_precision"] <= 1.0
    assert 0.0 <= aggregate["micro_recall"] <= 1.0
    assert aggregate["queries"] == len(first["per_query"])
    assert aggregate["true_positives"] == sum(row["true_positives"] for row in first["per_query"])
    assert aggregate["tokens_total"] == sum(row["tokens"] for row in first["per_query"])


def test_committed_report_matches_the_current_selection() -> None:
    assert dr.main(["--root", str(ROOT), "--check"]) == 0


def test_apply_then_check_roundtrip_and_tamper_detection(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "tests" / "eval", tmp_path / "tests" / "eval")
    (tmp_path / "docs").mkdir()

    assert dr.main(["--root", str(tmp_path), "--apply"]) == 0
    assert dr.main(["--root", str(tmp_path), "--check"]) == 0

    report = tmp_path / dr.REPORT_RELATIVE_PATH
    tampered = report.read_text(encoding="utf-8").replace(
        '"empty_answers": 0', '"empty_answers": 99'
    )
    report.write_text(tampered, encoding="utf-8")
    assert dr.main(["--root", str(tmp_path), "--check"]) == 1
