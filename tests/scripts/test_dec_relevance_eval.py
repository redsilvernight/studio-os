"""The decision-relevance evaluation is deterministic, self-consistent, and the
P07 selection clears the bars P00 left open (measured, not asserted by hand)."""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from scripts import dec_relevance_eval as dr

ROOT = Path(__file__).resolve().parents[2]

# P07 targets, from `docs/DEC_RELEVANCE_P07.md`.
MIN_MICRO_PRECISION = 0.35
MIN_MICRO_RECALL = 0.70
MAX_EMPTY_RATE = 0.05


def _load() -> tuple[dict, list]:
    queries = dr.load_queries(ROOT / dr.QUERIES_RELATIVE_PATH)
    corpus = dr.load_corpus(ROOT / dr.CORPUS_RELATIVE_PATH)
    return queries, corpus


def _kwargs() -> dict:
    selection = dr.load_queries(ROOT / dr.QUERIES_RELATIVE_PATH)["selection"]
    return {"limit": selection["limit"], "max_chars": selection["max_chars"]}


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
    kwargs = _kwargs()

    first = asyncio.run(dr.run_eval(queries, corpus, **kwargs))
    second = asyncio.run(dr.run_eval(queries, corpus, **kwargs))
    assert first == second

    aggregate = first["aggregate"]
    assert 0.0 <= aggregate["micro_precision"] <= 1.0
    assert 0.0 <= aggregate["micro_recall"] <= 1.0
    assert aggregate["queries"] == len(first["per_query"])
    assert aggregate["true_positives"] == sum(row["true_positives"] for row in first["per_query"])
    assert aggregate["tokens_total"] == sum(row["tokens"] for row in first["per_query"])


def test_selection_clears_the_p07_targets_under_the_p00_token_budget() -> None:
    queries, corpus = _load()
    baseline = dr.load_baseline(ROOT / dr.BASELINE_RELATIVE_PATH)
    assert baseline is not None, "the frozen P00 block is the comparison reference"
    metrics = asyncio.run(dr.run_eval(queries, corpus, baseline=baseline, **_kwargs()))
    aggregate = metrics["aggregate"]

    assert aggregate["micro_precision"] >= MIN_MICRO_PRECISION
    assert aggregate["micro_recall"] >= MIN_MICRO_RECALL
    assert aggregate["empty_rate"] <= MAX_EMPTY_RATE
    assert aggregate["tokens_total"] <= baseline["aggregate"]["tokens_total"]
    assert aggregate["micro_precision"] > baseline["aggregate"]["micro_precision"]
    # No expected decision is dropped for a reason no lexical rule could fix.
    for row in metrics["per_query"]:
        for readable_id in row["lexically_unreachable"]:
            assert readable_id in row["expected"]


def test_committed_report_matches_the_current_selection() -> None:
    assert dr.main(["--root", str(ROOT), "--check"]) == 0


def test_apply_then_check_roundtrip_and_tamper_detection(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "tests" / "eval", tmp_path / "tests" / "eval")
    (tmp_path / "docs").mkdir()
    # No baseline file there: the report must still be written, with "—" columns.
    assert dr.main(["--root", str(tmp_path), "--apply"]) == 0
    assert dr.main(["--root", str(tmp_path), "--check"]) == 0

    report = tmp_path / dr.REPORT_RELATIVE_PATH
    assert "P00" in report.read_text(encoding="utf-8")  # baseline columns, left empty
    tampered = report.read_text(encoding="utf-8").replace(
        '"empty_answers": 0', '"empty_answers": 99'
    )
    report.write_text(tampered, encoding="utf-8")
    assert dr.main(["--root", str(tmp_path), "--check"]) == 1
