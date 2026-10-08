"""Markdown export of the server decisions (P10).

The Studio OS server is the source of truth for decisions. `docs/decisions/`
and `docs/DECISIONS.md` are generated, never hand-edited:

    fetch    server -> docs/DEC_EXPORT.json (deterministic snapshot)
    render   snapshot -> docs/decisions/DEC-XXXX-slug.md + docs/DECISIONS.md
    compare  snapshot vs the current Markdown corpus: no DEC may be lost

Usage:
    uv run python -m scripts.dec_export fetch --project-id <uuid>
    uv run python -m scripts.dec_export render --check   # exit 1 if stale
    uv run python -m scripts.dec_export render --apply   # (re)write the export
    uv run python -m scripts.dec_export compare          # exit 1 if a DEC is lost

`fetch` reads `STUDIO_API_URL`, then the token from `STUDIO_TOKEN` or the
machine token store. The token is never printed.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from .adr_common import adr_filename, parse_adr_markdown, render_adr_markdown
from .adr_index import INDEX_RELPATH, PREAMBLE_FILENAME, render_index_entries

DEC_EXPORT_FORMAT = "studio-dec-export/1"
SNAPSHOT_RELPATH = "docs/DEC_EXPORT.json"
DECISIONS_DIR_RELPATH = "docs/decisions"
EXPORT_SOURCE = "server-export"
DEC_ID_RE = re.compile(r"\bDEC-\d{4,}\b")
_DECISION_STATUSES = {"proposed", "accepted", "superseded"}
_NOTE_STATUS = {"validated": "accepted", "superseded": "superseded"}
_LEADING_HEADING_RE = re.compile(r"\A\s*#\s+DEC-\d+[^\n]*\n+")
_VAULT_PAGE_LIMIT = 200


def _dec_num(readable_id: str) -> int:
    return int(readable_id.split("-", 1)[1])


def _norm_title(title: str) -> str:
    return re.sub(r"^\s*(DEC-\d+\s*[—:-]?\s*)", "", title).strip().lower()


def same_title(a: str, b: str) -> bool:
    """Same decision? Ratio threshold of the P08 import (collision < 0.5)."""
    return difflib.SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio() >= 0.5


def _date(value: Any) -> str | None:
    return str(value)[:10] if value else None


def build_snapshot(
    project_id: str,
    decisions: Iterable[dict[str, Any]],
    notes: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Pure merge of server decisions and their vault notes.

    The numbered vault note wins (DEC-0192: on a number collision the
    imported file content is the decision, the server row a legacy variant):
    title, status and body come from it, `supersedes` links too. The Decision
    row fills date and task only when it is the same decision (similar
    title), and stands alone when it has no note.
    """
    note_by_id = {
        n["readable_id"]: n
        for n in notes
        if n.get("note_type") == "decision" and DEC_ID_RE.fullmatch(n.get("readable_id") or "")
    }
    note_id_to_readable = {n["id"]: rid for rid, n in note_by_id.items() if n.get("id")}
    decision_by_id = {d["readable_id"]: d for d in decisions}

    entries: dict[str, dict[str, Any]] = {}
    for rid, d in decision_by_id.items():
        if rid in note_by_id:
            continue
        entries[rid] = {
            "readable_id": rid,
            "title": d["title"],
            "status": d["status"] if d["status"] in _DECISION_STATUSES else "proposed",
            "date": _date(d.get("created_at")),
            "task_id": d.get("task_id"),
            "body": d.get("body") or "",
            "body_source": "decision",
        }
    for rid, note in note_by_id.items():
        title = note.get("title") or rid
        d = decision_by_id.get(rid)
        same = d is not None and same_title(d["title"], title)
        entries[rid] = {
            "readable_id": rid,
            "title": title,
            "status": _NOTE_STATUS.get(note.get("status") or "", "proposed"),
            "date": _date(d.get("created_at") if same and d else note.get("created_at")),
            "task_id": d.get("task_id") if same and d else None,
            "body": note.get("body") or "",
            "body_source": "vault",
        }

    supersedes: dict[str, set[str]] = {rid: set() for rid in entries}
    superseded_by: dict[str, set[str]] = {rid: set() for rid in entries}
    for rid, note in note_by_id.items():
        for link in note.get("links") or []:
            if link.get("kind") != "supersedes":
                continue
            old = note_id_to_readable.get(link.get("target_note_id"))
            if old and old != rid and old in entries:
                supersedes[rid].add(old)
                superseded_by[old].add(rid)

    ordered = []
    for rid in sorted(entries, key=_dec_num):
        e = entries[rid]
        ordered.append(
            {
                "readable_id": rid,
                "title": e["title"],
                "status": e["status"],
                "date": e["date"],
                "task_id": e["task_id"],
                "supersedes": sorted(supersedes[rid], key=_dec_num),
                "superseded_by": sorted(superseded_by[rid], key=_dec_num),
                "body": e["body"],
                "body_source": e["body_source"],
            }
        )
    return {"format": DEC_EXPORT_FORMAT, "project_id": project_id, "decisions": ordered}


def dump_snapshot(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"


def load_snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != DEC_EXPORT_FORMAT:
        raise ValueError(f"{path}: format attendu {DEC_EXPORT_FORMAT!r}")
    return data


# --- fetch ---------------------------------------------------------------


def _resolve_token(api_url: str) -> str:
    token = os.environ.get("STUDIO_TOKEN")
    if token:
        return token
    from studio_client.tokens import origin_of, resolve_token

    return resolve_token(origin_of(api_url))


def fetch_snapshot(client: httpx.Client, project_id: str) -> dict[str, Any]:
    resp = client.get("/api/v1/decisions", params={"project_id": project_id})
    resp.raise_for_status()
    decisions = resp.json()
    if isinstance(decisions, dict):
        decisions = decisions.get("items", [])

    summaries: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {
            "scope": "project",
            "project_id": project_id,
            "limit": _VAULT_PAGE_LIMIT,
        }
        if cursor:
            params["cursor"] = cursor
        page = client.get("/api/v1/vault/tree", params=params)
        if page.status_code == 404 and cursor is None:
            break  # server without the vault API: decisions alone
        page.raise_for_status()
        data = page.json()
        summaries.extend(data.get("items", []))
        cursor = data.get("next_cursor")
        if not cursor:
            break

    notes = []
    for s in summaries:
        if s.get("note_type") != "decision" or not DEC_ID_RE.fullmatch(s.get("readable_id") or ""):
            continue
        full = client.get(f"/api/v1/vault/notes/{s['id']}")
        full.raise_for_status()
        notes.append({**s, **full.json()})
    return build_snapshot(project_id, decisions, notes)


# --- render --------------------------------------------------------------


def _clean_body(body: str) -> str:
    return _LEADING_HEADING_RE.sub("", body.replace("\r\n", "\n")).strip()


def render_files(snapshot: dict[str, Any], preamble: str | None) -> dict[str, str]:
    """Relative path (under docs/) -> content, for the whole export."""
    files: dict[str, str] = {}
    entries = []
    for d in snapshot["decisions"]:
        name = adr_filename(d["readable_id"], d["title"])
        fields = {
            "id": d["readable_id"],
            "title": d["title"],
            "status": d["status"],
            "date": d["date"],
            "supersedes": d["supersedes"],
            "superseded_by": d["superseded_by"],
            "source": EXPORT_SOURCE,
        }
        files[f"decisions/{name}"] = render_adr_markdown(fields, _clean_body(d["body"]))
        entries.append({**fields, "_relpath": f"decisions/{name}"})
    files[Path(INDEX_RELPATH).name] = render_index_entries(entries, preamble)
    return files


def plan_render(root: Path, snapshot: dict[str, Any]) -> tuple[dict[str, str], list[Path]]:
    """(files to write: abs path -> content, stale .md files to delete)."""
    docs = root / "docs"
    decisions_dir = root / DECISIONS_DIR_RELPATH
    preamble_path = decisions_dir / PREAMBLE_FILENAME
    preamble = preamble_path.read_text(encoding="utf-8") if preamble_path.exists() else None
    rendered = {docs / rel: content for rel, content in render_files(snapshot, preamble).items()}
    stale = []
    if decisions_dir.exists():
        stale = sorted(
            p
            for p in decisions_dir.glob("*.md")
            if not p.name.startswith("_") and p not in rendered
        )
    changed = {
        path: content
        for path, content in rendered.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    }
    return changed, stale


# --- compare -------------------------------------------------------------


def corpus_titles(root: Path) -> dict[str, str]:
    """Every DEC id the current Markdown corpus knows about -> its title."""
    titles: dict[str, str] = {}
    index = root / INDEX_RELPATH
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines():
            if line.startswith("| DEC-"):
                cells = [c.strip() for c in line.split("|")]
                titles[cells[1]] = cells[2].replace(r"\|", "|")
    decisions_dir = root / DECISIONS_DIR_RELPATH
    for path in sorted(decisions_dir.glob("*.md")) if decisions_dir.exists() else []:
        if path.name.startswith("_"):
            continue
        fields, _ = parse_adr_markdown(path.read_text(encoding="utf-8"))
        for key in ("id", "server_readable_id"):
            value = fields.get(key)
            if isinstance(value, str) and DEC_ID_RE.fullmatch(value):
                titles[value] = str(fields.get("title") or "")
    return titles


def compare(root: Path, snapshot: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(lost ids, extra ids) between the Markdown corpus and the snapshot. An
    id exported with a different decision (number collision) is lost too."""
    exported = {d["readable_id"]: d["title"] for d in snapshot["decisions"]}
    known = corpus_titles(root)
    lost = [
        rid
        for rid, title in known.items()
        if rid not in exported or (title and not same_title(title, exported[rid]))
    ]
    extra = [rid for rid in exported if rid not in known]
    return sorted(lost, key=_dec_num), sorted(extra, key=_dec_num)


# --- CLI -----------------------------------------------------------------


def _cmd_fetch(args: argparse.Namespace) -> int:
    api_url = args.api_url or os.environ.get("STUDIO_API_URL")
    project_id = args.project_id or os.environ.get("STUDIO_PROJECT_ID")
    if not api_url or not project_id:
        print("STUDIO_API_URL et --project-id (ou STUDIO_PROJECT_ID) sont requis.")
        return 2
    headers = {"Authorization": f"Bearer {_resolve_token(api_url)}"}
    with httpx.Client(base_url=api_url, headers=headers, timeout=30.0) as client:
        snapshot = fetch_snapshot(client, project_id)
    out = args.root / args.snapshot
    out.write_text(dump_snapshot(snapshot), encoding="utf-8", newline="\n")
    print(f"{args.snapshot} ecrit ({len(snapshot['decisions'])} decision(s)).")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    snapshot = load_snapshot(args.root / args.snapshot)
    changed, stale = plan_render(args.root, snapshot)
    if args.check:
        if not changed and not stale:
            print("Export des decisions a jour.")
            return 0
        for path in sorted(changed):
            print(f"perime : {path.relative_to(args.root).as_posix()}")
        for path in stale:
            print(f"orphelin : {path.relative_to(args.root).as_posix()}")
        print("Export perime -- relancer `render --apply`.")
        return 1
    for path, content in changed.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    for path in stale:
        path.unlink()
        print(f"supprime : {path.relative_to(args.root).as_posix()}")
    print(f"{len(changed)} fichier(s) ecrit(s), {len(stale)} supprime(s).")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    lost, extra = compare(args.root, load_snapshot(args.root / args.snapshot))
    for rid in extra:
        print(f"nouveau : {rid}")
    for rid in lost:
        print(f"PERDU : {rid}")
    print(f"{len(lost)} perdue(s), {len(extra)} nouvelle(s).")
    return 1 if lost else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "render", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, default=Path("."))
        p.add_argument("--snapshot", default=SNAPSHOT_RELPATH)
        if name == "fetch":
            p.add_argument("--api-url")
            p.add_argument("--project-id")
        if name == "render":
            mode = p.add_mutually_exclusive_group(required=True)
            mode.add_argument("--check", action="store_true")
            mode.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    handlers = {"fetch": _cmd_fetch, "render": _cmd_render, "compare": _cmd_compare}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
