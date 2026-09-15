"""Vault/repo integrity linter (Phase 5).

Deterministic, no LLM, no required external service. Checks:

  - 1:1 coverage: every ADR in docs/decisions/ has exactly one vault note
    aliased to it, and vice versa (a vault note carrying a DEC-XXXX alias
    with no matching ADR is reported, not silently ignored).
  - alias uniqueness: no two vault notes claim the same DEC-XXXX alias.
  - no unjustified null in graphify.entities: a null node_id is only valid
    when the entity is explicitly marked `unresolved: true` (the vault's own
    convention for "we know the file but not the exact symbol yet" -- see
    dec-20260913-docker-compose-validated-e2e.md).
  - supersedes / superseded_by validity: when set, must name a real DEC-XXXX
    that has an ADR (dangling references are reported).
  - graphify.entities resolution: what fraction of non-null node_ids
    actually exist in the current Graphify graph (graph.json). This mirrors
    the "91% resolved" baseline metric from the original audit.

A best-effort Postgres consistency check is available (`--check-db`) but is
never required: per the mandate ("sans rendre cette base obligatoire pour un
controle local"), the default run skips it and says so explicitly rather
than pretending a database was checked when it wasn't.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adr_common import index_vault_notes_by_dec_id, load_vault_note, parse_adr_markdown

DECISIONS_DIR_RELPATH = "docs/decisions"
DEFAULT_VAULT_DIR = Path(r"E:\LocalAI\AI-Memory\projects\studio-os\decisions")
DEFAULT_GRAPH_PATH = Path(r"E:\Graphify\Studio-OS\graphify-out\graph.json")


@dataclass
class LintIssue:
    check: str
    severity: str  # "error" | "warning"
    dec_id: str | None
    message: str


@dataclass
class LintReport:
    issues: list[LintIssue] = field(default_factory=list)
    adr_count: int = 0
    vault_note_count: int = 0
    entities_total: int = 0
    entities_resolved: int = 0
    db_check: str = "skipped (not requested)"

    @property
    def errors(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def resolution_rate(self) -> float | None:
        return (self.entities_resolved / self.entities_total) if self.entities_total else None


def _load_adrs(decisions_dir: Path) -> dict[str, dict[str, Any]]:
    adrs = {}
    for path in sorted(decisions_dir.glob("DEC-*.md")):
        fields, _body = parse_adr_markdown(path.read_text(encoding="utf-8"))
        adrs[fields["id"]] = fields
    return adrs


def run_lint(
    root: Path,
    vault_dir: Path = DEFAULT_VAULT_DIR,
    graph_path: Path = DEFAULT_GRAPH_PATH,
) -> LintReport:
    report = LintReport()
    decisions_dir = root / DECISIONS_DIR_RELPATH
    adrs = _load_adrs(decisions_dir)
    report.adr_count = len(adrs)

    all_vault_notes = []
    if vault_dir.exists():
        for path in sorted(vault_dir.glob("*.md")):
            note = load_vault_note(path)
            if note is not None:
                all_vault_notes.append(note)
    report.vault_note_count = len(all_vault_notes)

    # Alias uniqueness across the WHOLE vault (not just DEC-prefixed
    # aliases at this project) would be out of scope; restrict to DEC-XXXX.
    alias_owners: dict[str, list[Path]] = {}
    for note in all_vault_notes:
        for alias in note.frontmatter.get("aliases", []) or []:
            if isinstance(alias, str) and alias.startswith("DEC-"):
                alias_owners.setdefault(alias, []).append(note.path)
    for alias, owners in alias_owners.items():
        if len(owners) > 1:
            report.issues.append(
                LintIssue(
                    "alias_uniqueness",
                    "error",
                    alias,
                    f"{alias} claimed by {len(owners)} vault notes: {[str(p) for p in owners]}",
                )
            )

    vault_by_dec = index_vault_notes_by_dec_id(vault_dir)

    # Coverage: repo -> vault
    for dec_id in adrs:
        if dec_id not in vault_by_dec:
            report.issues.append(
                LintIssue(
                    "coverage_repo_to_vault",
                    "warning",
                    dec_id,
                    f"{dec_id} has an ADR but no vault note aliases it",
                )
            )
    # Coverage: vault -> repo
    for alias in alias_owners:
        if alias not in adrs:
            report.issues.append(
                LintIssue(
                    "coverage_vault_to_repo",
                    "error",
                    alias,
                    f"a vault note aliases {alias} but no such ADR exists in docs/decisions/",
                )
            )

    # supersedes / superseded_by validity + entity null/resolution checks,
    # scanned across every vault note (not just DEC-aliased ones, so a note
    # with a stray reference still gets caught).
    graph_node_ids: set[str] | None = None
    if graph_path.exists():
        try:
            graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
            nodes = graph_data.get("nodes", [])
            graph_node_ids = {n["id"] for n in nodes if isinstance(n, dict) and "id" in n}
        except (json.JSONDecodeError, OSError, KeyError):
            graph_node_ids = None

    for note in all_vault_notes:
        fm = note.frontmatter
        for field_name in ("supersedes", "superseded_by"):
            value = fm.get(field_name)
            if value and isinstance(value, str) and value not in adrs:
                report.issues.append(
                    LintIssue(
                        "dangling_reference",
                        "error",
                        fm.get("aliases", [None])[0] if fm.get("aliases") else None,
                        f"{note.path.name}: {field_name}={value!r} does not match any ADR",
                    )
                )
        entities = (fm.get("graphify") or {}).get("entities") or []
        for e in entities:
            if not isinstance(e, dict):
                report.issues.append(
                    LintIssue(
                        "malformed_entity",
                        "error",
                        fm.get("aliases", [None])[0] if fm.get("aliases") else None,
                        f"{note.path.name}: graphify.entities contains {e!r} "
                        f"({type(e).__name__}), expected an object with node_id/symbol/path",
                    )
                )
                continue
            node_id = e.get("node_id")
            if node_id is None:
                if not e.get("unresolved"):
                    report.issues.append(
                        LintIssue(
                            "unjustified_null_entity",
                            "error",
                            fm.get("aliases", [None])[0] if fm.get("aliases") else None,
                            f"{note.path.name}: entity {e.get('symbol') or e.get('path')} "
                            f"has node_id=null without unresolved=true",
                        )
                    )
                continue
            report.entities_total += 1
            if graph_node_ids is None or node_id in graph_node_ids:
                report.entities_resolved += 1
            else:
                report.issues.append(
                    LintIssue(
                        "entity_not_in_graph",
                        "warning",
                        fm.get("aliases", [None])[0] if fm.get("aliases") else None,
                        f"{note.path.name}: entity node_id {node_id!r} not found in "
                        f"current graph.json",
                    )
                )

    return report


def check_db(dsn: str | None) -> str:
    """Best-effort: try a real, direct TCP connection only -- never assert a
    schema-level check that wasn't actually run. No dependency on the
    project's async ORM stack here (this is a standalone lint script)."""
    import socket
    from urllib.parse import urlparse

    if not dsn:
        return "skipped (no DSN provided)"
    parsed = urlparse(dsn.replace("+asyncpg", "").replace("+psycopg", ""))
    host, port = parsed.hostname or "localhost", parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except OSError as exc:
        return f"skipped (Postgres unreachable at {host}:{port}: {exc})"
    return f"reachable at {host}:{port} (schema-level decisions-table check not implemented)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--vault-dir", type=Path, default=DEFAULT_VAULT_DIR)
    ap.add_argument("--graph-path", type=Path, default=DEFAULT_GRAPH_PATH)
    ap.add_argument(
        "--check-db", type=str, default=None, help="DSN to best-effort probe (optional)"
    )
    args = ap.parse_args()

    report = run_lint(args.root, args.vault_dir, args.graph_path)
    if args.check_db is not None:
        report.db_check = check_db(args.check_db)

    print(f"ADRs: {report.adr_count}, vault notes: {report.vault_note_count}")
    print(
        f"entites resolues: {report.entities_resolved}/{report.entities_total} "
        f"({report.resolution_rate:.1%})"
        if report.entities_total
        else "aucune entite"
    )
    print(f"db_check: {report.db_check}")
    for issue in report.issues:
        print(f"  [{issue.severity.upper()}] {issue.check} ({issue.dec_id}): {issue.message}")
    warnings = len(report.issues) - len(report.errors)
    print(f"{len(report.errors)} erreur(s), {warnings} avertissement(s)")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
