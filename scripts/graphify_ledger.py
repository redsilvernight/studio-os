"""Reliable, queryable Graphify cost ledger.

Extends the `cost.json` file the shared `graphify_incremental_update.py`
already writes (one aggregate entry per run: date, input/output tokens,
files, backends) with a per-attempt log under a new `"attempts"` key.

An "attempt" is one unit of extraction work actually dispatched to a backend
-- one AST call over a batch of native-code files (0 tokens, but a real,
*measured* zero), one Gemini call over a batch of native docs, or one
qwen/kimi call over one chunk of sidecar files. Token usage is only ever
known at that granularity (the backends return one usage total per call, not
per file), so an attempt's `files` field is a list, and per-file
`content_hashes`/`size_bytes` maps let reports still be sliced by file
without fabricating a false per-file token split.

Ne jamais convertir une mesure absente en zero: when a backend does not
report usage (or a value is not yet knowable), the corresponding
`input_tokens`/`output_tokens` field is `None` and `tokens_status` is
`"unmeasured"` -- callers must never coerce that to 0. Same principle for
`cost_usd`/`cost_status`.

Fully backward compatible: `load_ledger` reads a pre-Phase-3 `cost.json`
(just `{"runs": [...], "total_input_tokens": N, "total_output_tokens": N}`)
without error, and `record_attempts` never touches the existing `"runs"`
array.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2


def sha256_of(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@dataclass
class Attempt:
    date: str
    project: str
    files: list[str]
    backend: str
    processing_type: str  # "ast" | "semantic" | "sidecar"
    outcome: str  # "success" | "error"
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tokens_status: str = "unmeasured"  # "measured" | "unmeasured"
    cache: str = "unknown"  # "hit" | "miss" | "unknown"
    attempt_number: int = 1
    duration_s: float | None = None
    cost_usd: float | None = None
    cost_status: str = "unmeasured"  # "estimated" | "unmeasured" | "not_applicable"
    content_hashes: dict[str, str | None] = field(default_factory=dict)
    size_bytes: dict[str, int | None] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {k: v for k, v in self.__dict__.items()}


def build_attempt(
    *,
    project: str,
    files: list[str],
    root: Path,
    backend: str,
    processing_type: str,
    outcome: str,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache: str = "unknown",
    attempt_number: int = 1,
    duration_s: float | None = None,
    cost_usd: float | None = None,
    cost_status: str = "unmeasured",
    error: str | None = None,
) -> Attempt:
    tokens_status = (
        "measured" if input_tokens is not None and output_tokens is not None else "unmeasured"
    )
    content_hashes: dict[str, str | None] = {}
    size_bytes: dict[str, int | None] = {}
    for f in files:
        p = root / f
        content_hashes[f] = sha256_of(p) if p.exists() else None
        try:
            size_bytes[f] = p.stat().st_size if p.exists() else None
        except OSError:
            size_bytes[f] = None
    return Attempt(
        date=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        project=project,
        files=list(files),
        backend=backend,
        processing_type=processing_type,
        outcome=outcome,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tokens_status=tokens_status,
        cache=cache,
        attempt_number=attempt_number,
        duration_s=duration_s,
        cost_usd=cost_usd,
        cost_status=cost_status,
        content_hashes=content_hashes,
        size_bytes=size_bytes,
        error=error,
    )


def load_ledger(cost_path: Path) -> dict[str, Any]:
    """Read cost.json, tolerant of the pre-Phase-3 format. Never mutates the
    file; callers that want the upgraded shape persisted must write it back
    themselves (e.g. via record_attempts)."""
    if not cost_path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "runs": [],
            "attempts": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }
    data = json.loads(cost_path.read_text(encoding="utf-8"))
    return migrate_legacy(data)


def migrate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """Add the fields Phase 3 introduced if they are missing, without
    touching anything that was already there (including "runs")."""
    data = dict(data)
    data.setdefault("schema_version", 1 if "attempts" not in data else SCHEMA_VERSION)
    data.setdefault("runs", [])
    data.setdefault("attempts", [])
    data.setdefault("total_input_tokens", 0)
    data.setdefault("total_output_tokens", 0)
    data["schema_version"] = SCHEMA_VERSION
    return data


def record_attempts(cost_path: Path, attempts: list[Attempt]) -> dict[str, Any]:
    ledger = load_ledger(cost_path)
    for attempt in attempts:
        ledger["attempts"].append(attempt.to_dict())
        if attempt.tokens_status == "measured":
            ledger["total_input_tokens"] += attempt.input_tokens or 0
            ledger["total_output_tokens"] += attempt.output_tokens or 0
    cost_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    return ledger


# --- reports -----------------------------------------------------------


def cost_by_file(ledger: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "attempts": 0,
            "measured_attempts": 0,
            "unmeasured_attempts": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    )
    for a in ledger.get("attempts", []):
        for f in a.get("files", []):
            row = out[f]
            row["attempts"] += 1
            if a.get("tokens_status") == "measured":
                row["measured_attempts"] += 1
                row["input_tokens"] += a.get("input_tokens") or 0
                row["output_tokens"] += a.get("output_tokens") or 0
            else:
                row["unmeasured_attempts"] += 1
    return dict(out)


def cost_by_backend(ledger: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "attempts": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "unmeasured_attempts": 0,
        }
    )
    for a in ledger.get("attempts", []):
        row = out[a.get("backend", "unknown")]
        row["attempts"] += 1
        if a.get("tokens_status") == "measured":
            row["input_tokens"] += a.get("input_tokens") or 0
            row["output_tokens"] += a.get("output_tokens") or 0
        else:
            row["unmeasured_attempts"] += 1
    return dict(out)


def cost_by_period(ledger: dict[str, Any], granularity: str = "day") -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "attempts": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    )
    length = {"day": 10, "month": 7}.get(granularity, 10)
    for a in ledger.get("attempts", []):
        date = a.get("date", "")
        key = date[:length] if date else "unknown"
        row = out[key]
        row["attempts"] += 1
        if a.get("tokens_status") == "measured":
            row["input_tokens"] += a.get("input_tokens") or 0
            row["output_tokens"] += a.get("output_tokens") or 0
    return dict(out)


def ast_semantic_ratio(ledger: dict[str, Any]) -> dict[str, Any]:
    ast_files: set[str] = set()
    semantic_files: set[str] = set()
    for a in ledger.get("attempts", []):
        target = (
            ast_files
            if a.get("processing_type") == "ast"
            else (semantic_files if a.get("processing_type") in ("semantic", "sidecar") else None)
        )
        if target is not None:
            target.update(a.get("files", []))
    ast_count, semantic_count = len(ast_files), len(semantic_files)
    ratio = (ast_count / semantic_count) if semantic_count else None
    return {
        "ast_files": ast_count,
        "semantic_files": semantic_count,
        "ast_to_semantic_ratio": ratio,
    }


def top_cost_files(ledger: dict[str, Any], n: int = 10) -> list[tuple[str, int]]:
    totals = {
        f: row["input_tokens"] + row["output_tokens"] for f, row in cost_by_file(ledger).items()
    }
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:n]


def _main() -> int:
    ap = argparse.ArgumentParser(description="Query the Graphify cost ledger.")
    ap.add_argument("--cost-json", required=True, type=Path)
    ap.add_argument(
        "--by", choices=["file", "backend", "period", "ratio", "top"], default="backend"
    )
    ap.add_argument("--period-granularity", choices=["day", "month"], default="day")
    ap.add_argument("--top-n", type=int, default=10)
    args = ap.parse_args()

    ledger = load_ledger(args.cost_json)
    result: object
    if args.by == "file":
        result = cost_by_file(ledger)
    elif args.by == "backend":
        result = cost_by_backend(ledger)
    elif args.by == "period":
        result = cost_by_period(ledger, args.period_granularity)
    elif args.by == "ratio":
        result = ast_semantic_ratio(ledger)
    else:
        result = top_cost_files(ledger, args.top_n)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
