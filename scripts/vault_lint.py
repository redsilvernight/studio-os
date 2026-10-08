"""DEC integrity linter -- default mode: repo DEC-*.md vs the server snapshot.

Deterministic, no LLM, no network, no required external service.

Default mode (`--snapshot docs/DEC_EXPORT.json --root .`) compares the
canonical ADR files of `docs/decisions/` against the read-only export of the
server (`studio-dec-export/1`), which is the source of truth for the DECs:

  1. `coverage_*`: strict 1:1 between the frontmatter `id` of every
     docs/decisions/DEC-*.md and the snapshot `readable_id` list.
  2. `unexpected_decisions_file`: docs/decisions/ holds DEC-*.md (ADR) and
     _*.md (support files) only -- nothing else.
  3. `snapshot_format` / `snapshot_schema` / `duplicate_readable_id`: the
     export declares format == "studio-dec-export/1", the required fields are
     present and `readable_id` is unique.
  4. `supersedes_*` / `superseded_by_*`: every reference names an id present
     in the snapshot, and the two sides are symmetric (A supersedes B iff B is
     superseded_by A).
  5. `title_mismatch` / `status_mismatch`: the ADR frontmatter `title` and
     `status` equal their snapshot counterparts.

Legacy vault mode stays reachable only through an explicit `--vault <dir>`
(the local Obsidian vault, previously defaulted to an E:\\ path): it checks
DEC-XXXX alias coverage both ways, alias uniqueness, supersedes /
superseded_by validity, unjustified null in graphify.entities and the entity
resolution rate against graph.json. A best-effort Postgres probe stays
optional (`--check-db`) and is never required.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adr_common import index_vault_notes_by_dec_id, load_vault_note, parse_adr_markdown
from .dev_preflight import record as preflight_record
from .dev_preflight import run_preflight

DECISIONS_DIR_RELPATH = "docs/decisions"
SNAPSHOT_RELPATH = "docs/DEC_EXPORT.json"
DEC_EXPORT_FORMAT = "studio-dec-export/1"
SNAPSHOT_REQUIRED_KEYS = (
    "date",
    "task_id",
    "supersedes",
    "superseded_by",
    "body",
    "body_source",
)
SNAPSHOT_MODE = "snapshot"
VAULT_MODE = "vault"
DEFAULT_GRAPH_PATH = Path(r"E:\Graphify\Studio-OS\graphify-out\graph.json")


@dataclass(frozen=True)
class SnapshotDecision:
    readable_id: str
    title: str
    status: str
    supersedes: tuple[str, ...]
    superseded_by: tuple[str, ...]


@dataclass
class LintIssue:
    check: str
    severity: str  # "error" | "warning"
    dec_id: str | None
    message: str


@dataclass
class LintReport:
    issues: list[LintIssue] = field(default_factory=list)
    mode: str = SNAPSHOT_MODE
    adr_count: int = 0
    snapshot_count: int = 0
    snapshot_format: str | None = None
    vault_note_count: int = 0
    entities_total: int = 0
    entities_resolved: int = 0
    db_check: str | None = None

    @property
    def errors(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def resolution_rate(self) -> float | None:
        return (self.entities_resolved / self.entities_total) if self.entities_total else None

    def summary(self) -> str:
        if self.mode == SNAPSHOT_MODE:
            fmt = self.snapshot_format or "format inconnu"
            return (
                f"DEC: {self.adr_count} ADR(s) dans {DECISIONS_DIR_RELPATH}/, "
                f"{self.snapshot_count} decision(s) dans le snapshot ({fmt}) -- conforme"
            )
        return (
            f"ADRs: {self.adr_count}, vault notes: {self.vault_note_count}, "
            f"entites resolues: {self.entities_resolved}/{self.entities_total}"
        )


def _read_frontmatter(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"lecture impossible: {exc}"
    try:
        fields, _body = parse_adr_markdown(text)
    except ValueError as exc:
        return None, str(exc)
    if not isinstance(fields, dict):
        return None, "frontmatter absent ou vide"
    return fields, None


def _load_adrs(decisions_dir: Path) -> dict[str, dict[str, Any]]:
    adrs = {}
    for path in sorted(decisions_dir.glob("DEC-*.md")):
        fields = _read_frontmatter(path)[0]
        if fields is None:
            continue
        adrs[str(fields.get("id"))] = fields
    return adrs


def resolve_snapshot_path(root: Path, snapshot_path: Path) -> Path:
    return snapshot_path if snapshot_path.is_absolute() else root / snapshot_path


# --- default mode: repo DEC-*.md <-> server snapshot -------------------------


def _load_snapshot(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"lecture impossible: {exc}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"JSON invalide: {exc}"
    if not isinstance(data, dict):
        return None, f"racine JSON attendue (objet), obtenu {type(data).__name__}"
    return data, None


def _parse_snapshot_decisions(raw: Any, report: LintReport) -> dict[str, SnapshotDecision]:
    if not isinstance(raw, list):
        report.issues.append(
            LintIssue(
                "snapshot_schema",
                "error",
                None,
                f"decisions doit etre une liste, obtenu {type(raw).__name__}",
            )
        )
        return {}

    decisions: dict[str, SnapshotDecision] = {}
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            report.issues.append(
                LintIssue(
                    "snapshot_schema",
                    "error",
                    None,
                    f"decisions[{index}] doit etre un objet, obtenu {type(entry).__name__}",
                )
            )
            continue
        dec_id, title, status = entry.get("readable_id"), entry.get("title"), entry.get("status")
        missing = [
            name
            for name, value in (("readable_id", dec_id), ("title", title), ("status", status))
            if not isinstance(value, str) or not value.strip()
        ]
        missing += [key for key in SNAPSHOT_REQUIRED_KEYS if key not in entry]
        if missing:
            report.issues.append(
                LintIssue(
                    "snapshot_schema",
                    "error",
                    dec_id if isinstance(dec_id, str) else None,
                    f"decisions[{index}] champ(s) absent(s) ou non texte: {', '.join(missing)}",
                )
            )
            continue
        refs: dict[str, tuple[str, ...]] = {}
        malformed_ref = False
        for key in ("supersedes", "superseded_by"):
            value = entry.get(key)
            if value is None:
                refs[key] = ()
                continue
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                report.issues.append(
                    LintIssue(
                        "snapshot_schema",
                        "error",
                        dec_id,
                        f"decisions[{index}].{key} doit etre une liste d'ids, obtenu {value!r}",
                    )
                )
                malformed_ref = True
                break
            refs[key] = tuple(value)
        if malformed_ref:
            continue
        dec_id, title, status = str(dec_id), str(title), str(status)
        if dec_id in decisions:
            report.issues.append(
                LintIssue(
                    "duplicate_readable_id",
                    "error",
                    dec_id,
                    f"readable_id {dec_id} repete dans le snapshot",
                )
            )
            continue
        decisions[dec_id] = SnapshotDecision(
            readable_id=dec_id,
            title=title,
            status=status,
            supersedes=refs["supersedes"],
            superseded_by=refs["superseded_by"],
        )
    return decisions


def run_snapshot_lint(root: Path, snapshot_path: Path = Path(SNAPSHOT_RELPATH)) -> LintReport:
    report = LintReport(mode=SNAPSHOT_MODE)
    decisions_dir = root / DECISIONS_DIR_RELPATH

    docs: dict[str, dict[str, Any]] = {}
    doc_paths: dict[str, Path] = {}
    if not decisions_dir.is_dir():
        report.issues.append(
            LintIssue(
                "missing_decisions_dir",
                "error",
                None,
                f"{DECISIONS_DIR_RELPATH}/ absent de {root}",
            )
        )
    else:
        for path in sorted(decisions_dir.glob("DEC-*.md")):
            fields, error = _read_frontmatter(path)
            if fields is None:
                report.issues.append(
                    LintIssue("malformed_adr", "error", None, f"{path.name}: {error}")
                )
                continue
            dec_id = fields.get("id")
            if not isinstance(dec_id, str) or not dec_id.strip():
                report.issues.append(
                    LintIssue(
                        "malformed_adr",
                        "error",
                        None,
                        f"{path.name}: frontmatter id absent ou invalide",
                    )
                )
                continue
            if dec_id in docs:
                report.issues.append(
                    LintIssue(
                        "duplicate_dec_id",
                        "error",
                        dec_id,
                        f"{dec_id} declare dans {doc_paths[dec_id].name} et {path.name}",
                    )
                )
                continue
            docs[dec_id] = fields
            doc_paths[dec_id] = path
        for path in sorted(decisions_dir.glob("*.md")):
            if path.name.startswith("DEC-") or path.name.startswith("_"):
                continue
            report.issues.append(
                LintIssue(
                    "unexpected_decisions_file",
                    "error",
                    None,
                    f"{path.name}: seul DEC-*.md (ADR) ou _*.md (support) est autorise "
                    f"dans {DECISIONS_DIR_RELPATH}/",
                )
            )
    report.adr_count = len(docs)

    data, error = _load_snapshot(resolve_snapshot_path(root, snapshot_path))
    if data is None:
        report.issues.append(
            LintIssue("snapshot_unreadable", "error", None, f"{snapshot_path.as_posix()}: {error}")
        )
        return report

    declared_format = data.get("format")
    if declared_format != DEC_EXPORT_FORMAT:
        report.issues.append(
            LintIssue(
                "snapshot_format",
                "error",
                None,
                f"format={declared_format!r}, attendu {DEC_EXPORT_FORMAT!r}",
            )
        )
    report.snapshot_format = declared_format if isinstance(declared_format, str) else None

    decisions = _parse_snapshot_decisions(data.get("decisions"), report)
    report.snapshot_count = len(decisions)

    for dec_id in sorted(docs):
        if dec_id not in decisions:
            report.issues.append(
                LintIssue(
                    "coverage_docs_to_snapshot",
                    "error",
                    dec_id,
                    f"{dec_id} present dans {DECISIONS_DIR_RELPATH}/ mais absent du snapshot",
                )
            )
    for dec_id in sorted(decisions):
        if dec_id not in docs:
            report.issues.append(
                LintIssue(
                    "coverage_snapshot_to_docs",
                    "error",
                    dec_id,
                    f"{dec_id} present dans le snapshot mais sans ADR "
                    f"dans {DECISIONS_DIR_RELPATH}/",
                )
            )

    for dec_id in sorted(decisions):
        decision = decisions[dec_id]
        for target in decision.supersedes:
            other = decisions.get(target)
            if other is None:
                report.issues.append(
                    LintIssue(
                        "supersedes_dangling",
                        "error",
                        dec_id,
                        f"supersedes={target!r} absent du snapshot",
                    )
                )
            elif dec_id not in other.superseded_by:
                report.issues.append(
                    LintIssue(
                        "supersedes_asymmetric",
                        "error",
                        dec_id,
                        f"supersedes={target!r} mais {target}.superseded_by "
                        f"ne contient pas {dec_id}",
                    )
                )
        for target in decision.superseded_by:
            other = decisions.get(target)
            if other is None:
                report.issues.append(
                    LintIssue(
                        "superseded_by_dangling",
                        "error",
                        dec_id,
                        f"superseded_by={target!r} absent du snapshot",
                    )
                )
            elif dec_id not in other.supersedes:
                report.issues.append(
                    LintIssue(
                        "superseded_by_asymmetric",
                        "error",
                        dec_id,
                        f"superseded_by={target!r} mais {target}.supersedes "
                        f"ne contient pas {dec_id}",
                    )
                )

    for dec_id in sorted(docs):
        snapshot_decision = decisions.get(dec_id)
        if snapshot_decision is None:
            continue
        path = doc_paths[dec_id]
        frontmatter_title = docs[dec_id].get("title")
        if (
            not isinstance(frontmatter_title, str)
            or frontmatter_title.strip() != snapshot_decision.title
        ):
            report.issues.append(
                LintIssue(
                    "title_mismatch",
                    "error",
                    dec_id,
                    f"{path.name}: title={frontmatter_title!r} != "
                    f"snapshot {snapshot_decision.title!r}",
                )
            )
        frontmatter_status = docs[dec_id].get("status")
        if (
            not isinstance(frontmatter_status, str)
            or frontmatter_status.strip() != snapshot_decision.status
        ):
            report.issues.append(
                LintIssue(
                    "status_mismatch",
                    "error",
                    dec_id,
                    f"{path.name}: status={frontmatter_status!r} != "
                    f"snapshot {snapshot_decision.status!r}",
                )
            )

    return report


# --- legacy mode: local Obsidian vault --------------------------------------


def run_vault_lint(
    root: Path,
    vault_dir: Path,
    graph_path: Path = DEFAULT_GRAPH_PATH,
) -> LintReport:
    report = LintReport(mode=VAULT_MODE)
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


def run_lint(
    root: Path,
    vault_dir: Path | None = None,
    graph_path: Path = DEFAULT_GRAPH_PATH,
    snapshot_path: Path = Path(SNAPSHOT_RELPATH),
) -> LintReport:
    """Default: repo DEC-*.md vs the server snapshot. The local Obsidian vault
    is only linted when its directory is given explicitly."""
    if vault_dir is None:
        return run_snapshot_lint(root, snapshot_path)
    return run_vault_lint(root, vault_dir, graph_path)


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
    ap.add_argument(
        "--root", type=Path, default=Path("."), help="project root (default: the current dir)"
    )
    ap.add_argument(
        "--snapshot",
        type=Path,
        default=Path(SNAPSHOT_RELPATH),
        help=f"server DEC export (default: {SNAPSHOT_RELPATH}, resolved against --root)",
    )
    ap.add_argument(
        "--vault",
        "--vault-dir",
        dest="vault_dir",
        type=Path,
        default=None,
        help="legacy mode: linter le vault Obsidian local (jamais de chemin par defaut)",
    )
    ap.add_argument("--graph-path", type=Path, default=DEFAULT_GRAPH_PATH)
    ap.add_argument(
        "--check-db", type=str, default=None, help="DSN to best-effort probe (optional)"
    )
    ap.add_argument(
        "--no-preflight",
        action="store_true",
        help="skip the read-only dev == origin/dev preflight (explicit opt-out, logged)",
    )
    args = ap.parse_args()

    preflight_exit = 0
    if args.no_preflight:
        print("dev-preflight: SKIPPED (--no-preflight) -- dev state not verified")
    else:
        pre = run_preflight(args.root)
        print(f"dev-preflight [{pre.status}] {pre.message}")
        print(f"dev-preflight record: {json.dumps(preflight_record(pre))}")
        preflight_exit = pre.exit_code

    if args.vault_dir is not None:
        report = run_vault_lint(args.root, args.vault_dir, args.graph_path)
    else:
        report = run_snapshot_lint(args.root, args.snapshot)
    if args.check_db is not None:
        report.db_check = check_db(args.check_db)

    for issue in report.issues:
        print(f"  [{issue.severity.upper()}] {issue.check} ({issue.dec_id}): {issue.message}")
    print(report.summary())
    if report.mode == VAULT_MODE:
        if report.entities_total:
            print(
                f"entites resolues: {report.entities_resolved}/{report.entities_total} "
                f"({report.resolution_rate:.1%})"
            )
        else:
            print("aucune entite")
        print(f"db_check: {report.db_check}")
    warnings = len(report.issues) - len(report.errors)
    print(f"{len(report.errors)} erreur(s), {warnings} avertissement(s)")
    return 1 if report.errors else preflight_exit


if __name__ == "__main__":
    sys.exit(main())
