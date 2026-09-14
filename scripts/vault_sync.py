"""Idempotent ADR -> AI-Memory vault sync (Phase 5).

The vault note is a projection, never the source of truth: this sync only
ever touches a small, explicit set of *managed* fields, derived from the
ADR. Everything else in a vault note -- body prose (Contexte/Decision/
Consequences/Preuves/Liens), `aliases`, `dedupe_key`, `tags`, `confidence`,
`created` -- is human-curated and is preserved byte-for-byte.

Identity: a vault note belongs to an ADR when the note's `aliases` list
contains that ADR's `DEC-XXXX` id (mandate: "utiliser dedupe_key et l'alias
DEC-XXXX comme identites stables"). When no vault note carries that alias, a
new one is created (mandate: "creer une note si elle n'existe pas") with
only the fields actually known from the ADR -- see plan_create. Conversely,
a vault note with a DEC-XXXX alias that has NO matching ADR (e.g. a decision
that turned out never to have been formally numbered, see
dec-20260913-docker-compose-validated-e2e.md, which correctly carries no
DEC alias at all) is out of scope for this sync; the integrity linter
(vault_lint.py) reports that case instead of this tool guessing a match.

Managed fields (the only ones a sync ever writes):
  - `status`, `supersedes`, `superseded_by`: filled in when the vault note
    doesn't have them yet. When both sides already have a value and they
    disagree, that's a conflict -- reported, never silently overwritten.
  - `sources`: the ADR's own path is appended if not already listed
    (existing entries, e.g. the historical docs/DECISIONS.md reference,
    are never removed).
  - `graphify.entities`: additive union by `node_id` -- entities already in
    the vault are kept as-is; entities present on the ADR but missing from
    the vault are added. Nothing is ever removed here (that would need a
    human decision, not a sync).
  - `adr_sync`: bookkeeping block (`path`, `sync_hash`, `synced_at`) so a
    later run can tell whether the ADR changed since the last sync.

Everything else on the note is passed through unchanged.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .adr_common import (
    VaultNote,
    content_hash,
    index_vault_notes_by_dec_id,
    parse_adr_markdown,
    slugify,
)

DECISIONS_DIR_RELPATH = "docs/decisions"
DEFAULT_VAULT_DIR = Path(r"E:\LocalAI\AI-Memory\projects\studio-os\decisions")
MANAGED_SCALAR_FIELDS = ("status", "supersedes", "superseded_by")
GRAPH_ROOT = r"E:\Graphify\Studio-OS\graphify-out\graph.json"


@dataclass
class Conflict:
    dec_id: str
    field: str
    adr_value: object
    vault_value: object


@dataclass
class SyncAction:
    dec_id: str
    kind: str  # "create" | "update" | "unchanged" | "no_vault_match"
    vault_path: Path | None
    new_frontmatter: dict | None = None
    new_body: str | None = None
    conflicts: list[Conflict] = field(default_factory=list)


@dataclass
class SyncPlan:
    actions: list[SyncAction]

    @property
    def conflicts(self) -> list[Conflict]:
        return [c for a in self.actions for c in a.conflicts]


def _merge_entities(vault_entities: list, adr_entities: list) -> tuple[list, bool]:
    """Additive union keyed by node_id (falling back to (path, symbol) for
    unresolved entries with node_id=None). Returns (merged, changed)."""
    vault_entities = list(vault_entities or [])
    adr_entities = list(adr_entities or [])

    def key(e: dict) -> tuple:
        return (e.get("node_id"), e.get("path"), e.get("symbol"))

    existing_keys = {key(e) for e in vault_entities}
    changed = False
    merged = list(vault_entities)
    for e in adr_entities:
        if key(e) not in existing_keys:
            merged.append(e)
            existing_keys.add(key(e))
            changed = True
    return merged, changed


def _new_note_path(vault_dir: Path, dec_id: str, title: str) -> Path:
    today = time.strftime("%Y%m%d", time.gmtime())
    return vault_dir / f"dec-{today}-{slugify(title)}.md"


def plan_create(dec_id: str, adr_fields: dict, adr_path: Path, vault_dir: Path) -> SyncAction:
    """No vault note aliases this ADR yet -- build one from scratch. Only
    fields the ADR (or the sync operation itself) actually knows are
    written: no fabricated Contexte/Consequences/Preuves sections, no
    invented status/confidence. `created`/`updated` are the true date of
    this vault projection being created, not a guess at the decision's own
    (unknown) date."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    title = adr_fields["title"]
    adr_relpath = f"{DECISIONS_DIR_RELPATH}/{adr_path.name}"
    slug = slugify(title)

    fm: dict = {
        "aliases": [dec_id],
        "dedupe_key": f"decision:studio-os:{slug}",
        "project": "studio-os",
        "type": "decision",
        "schema_version": 1,
        "title": f"{dec_id} — {title}",
        "created": today,
        "updated": today,
        "sources": [adr_relpath, adr_fields.get("source", "docs/DECISIONS.md")],
        "tags": ["studio-os"],
        "graph_root": GRAPH_ROOT,
    }
    for f in MANAGED_SCALAR_FIELDS:
        if adr_fields.get(f) is not None:
            fm[f] = adr_fields[f]
    if adr_fields.get("graphify_entities"):
        fm["graphify"] = {"entities": adr_fields["graphify_entities"]}

    sync_hash = content_hash(f"{title}\n{adr_path.read_text(encoding='utf-8')}")
    fm["adr_sync"] = {
        "path": adr_relpath, "sync_hash": sync_hash,
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    _fields, body = parse_adr_markdown(adr_path.read_text(encoding="utf-8"))
    note_body = (
        f"# {dec_id} — {title}\n\n"
        f"## Decision\n\n{body}\n\n"
        f"## Preuves\n\n"
        f"Synchronise automatiquement depuis `{adr_relpath}`. Aucune revue "
        f"humaine effectuee sur cette note -- Contexte/Consequences a completer.\n"
    )
    return SyncAction(
        dec_id=dec_id, kind="create", vault_path=_new_note_path(vault_dir, dec_id, title),
        new_frontmatter=fm, new_body=note_body,
    )


def plan_one(dec_id: str, adr_fields: dict, adr_path: Path, vault_note, vault_dir: Path) -> SyncAction:
    sync_hash = content_hash(
        f"{adr_fields.get('title', '')}\n{adr_path.read_text(encoding='utf-8')}"
    )

    if vault_note is None:
        return plan_create(dec_id, adr_fields, adr_path, vault_dir)

    fm = dict(vault_note.frontmatter)
    conflicts: list[Conflict] = []
    changed = False

    for f in MANAGED_SCALAR_FIELDS:
        adr_value = adr_fields.get(f)
        if adr_value is None:
            continue
        vault_value = fm.get(f)
        if vault_value in (None, ""):
            fm[f] = adr_value
            changed = True
        elif vault_value != adr_value:
            conflicts.append(
                Conflict(dec_id=dec_id, field=f, adr_value=adr_value, vault_value=vault_value)
            )

    sources = list(fm.get("sources") or [])
    adr_relpath = f"{DECISIONS_DIR_RELPATH}/{adr_path.name}"
    if adr_relpath not in sources and str(adr_path) not in sources:
        sources.append(adr_relpath)
        fm["sources"] = sources
        changed = True

    adr_entities = adr_fields.get("graphify_entities") or []
    if adr_entities:
        graphify_block = dict(fm.get("graphify") or {})
        merged, entities_changed = _merge_entities(
            graphify_block.get("entities") or [], adr_entities
        )
        if entities_changed:
            graphify_block["entities"] = merged
            fm["graphify"] = graphify_block
            changed = True

    prior_sync = fm.get("adr_sync") or {}
    if prior_sync.get("sync_hash") != sync_hash:
        fm["adr_sync"] = {
            "path": adr_relpath,
            "sync_hash": sync_hash,
            "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        changed = True

    if not changed:
        return SyncAction(
            dec_id=dec_id, kind="unchanged", vault_path=vault_note.path, conflicts=conflicts
        )
    return SyncAction(
        dec_id=dec_id,
        kind="update",
        vault_path=vault_note.path,
        new_frontmatter=fm,
        new_body=vault_note.body,
        conflicts=conflicts,
    )


def plan_sync(root: Path, vault_dir: Path = DEFAULT_VAULT_DIR) -> SyncPlan:
    decisions_dir = root / DECISIONS_DIR_RELPATH
    vault_index = index_vault_notes_by_dec_id(vault_dir)

    actions: list[SyncAction] = []
    for adr_path in sorted(decisions_dir.glob("DEC-*.md")):
        adr_fields, _body = parse_adr_markdown(adr_path.read_text(encoding="utf-8"))
        dec_id = adr_fields["id"]
        vault_note = vault_index.get(dec_id)
        actions.append(plan_one(dec_id, adr_fields, adr_path, vault_note, vault_dir))
    return SyncPlan(actions=actions)


def apply_sync(plan: SyncPlan) -> None:
    for action in plan.actions:
        if action.kind not in ("update", "create") or action.vault_path is None:
            continue
        frontmatter = yaml.safe_dump(
            action.new_frontmatter, sort_keys=True, allow_unicode=True, default_flow_style=False
        )
        text = f"---\n{frontmatter}---\n{action.new_body}"
        action.vault_path.parent.mkdir(parents=True, exist_ok=True)
        action.vault_path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--vault-dir", type=Path, default=DEFAULT_VAULT_DIR)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    plan = plan_sync(args.root, args.vault_dir)
    by_kind: dict[str, int] = {}
    for a in plan.actions:
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
    print(f"sync: {by_kind}")
    for a in plan.actions:
        if a.kind == "update":
            print(f"  UPDATE {a.dec_id} -> {a.vault_path}")
        elif a.kind == "create":
            print(f"  CREATE {a.dec_id} -> {a.vault_path}")
    for c in plan.conflicts:
        print(
            f"  CONFLICT {c.dec_id}.{c.field}: adr={c.adr_value!r} "
            f"vault={c.vault_value!r} (not overwritten)"
        )

    if args.apply:
        apply_sync(plan)
        print("sync applique.")
    elif any(a.kind in ("update", "create") for a in plan.actions):
        return 1  # --check: non-zero means there is drift to apply
    return 0


if __name__ == "__main__":
    sys.exit(main())
