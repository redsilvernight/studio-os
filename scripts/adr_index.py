"""Idempotent generator for the compact `docs/DECISIONS.md` index, built
from the unit ADRs under `docs/decisions/` (Phase 4).

`docs/DECISIONS.md` keeps its historical path (nothing that already
references it breaks) but stops being hand-edited: it is regenerated here,
deterministically, from the ADR files' front matter. Running this twice with
no ADR changes produces byte-identical output.

Usage:
    uv run python -m scripts.adr_index --root . --check   # exit 1 if stale
    uv run python -m scripts.adr_index --root . --apply   # (re)write it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .adr_common import parse_adr_markdown

DECISIONS_DIR_RELPATH = "docs/decisions"
INDEX_RELPATH = "docs/DECISIONS.md"
PREAMBLE_FILENAME = "_preamble.md"

HEADER = """# Decisions log (index genere)

Ce fichier est genere par `uv run python -m scripts.adr_index` depuis les
ADR unitaires de `docs/decisions/`. Ne pas l'editer a la main -- une
modification directe sera ecrasee au prochain regenerat. Pour ajouter une
decision, creer un nouveau fichier `docs/decisions/DEC-XXXX-slug.md` (voir
un ADR existant comme modele), puis relancer la commande ci-dessus.
"""


def _dec_num(dec_id: str) -> int:
    return int(dec_id.split("-", 1)[1])


def load_adrs(decisions_dir: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(decisions_dir.glob("DEC-*.md")):
        fields, _body = parse_adr_markdown(path.read_text(encoding="utf-8"))
        entries.append({**fields, "_relpath": f"decisions/{path.name}"})
    entries.sort(key=lambda e: _dec_num(e["id"]))
    return entries


def render_index(decisions_dir: Path) -> str:
    entries = load_adrs(decisions_dir)
    preamble_path = decisions_dir / PREAMBLE_FILENAME
    parts = [HEADER]
    if preamble_path.exists():
        parts.append(preamble_path.read_text(encoding="utf-8").strip())
    parts.append(f"\n{len(entries)} decision(s). Detail complet dans chaque ADR lie.\n")
    table = ["| ID | Titre | Statut | ADR |", "|---|---|---|---|"]
    for e in entries:
        title = e["title"].replace("|", r"\|")
        status = e.get("status", "?")
        table.append(f"| {e['id']} | {title} | {status} | [{e['_relpath']}]({e['_relpath']}) |")
    parts.append("\n".join(table))
    return "\n\n".join(parts).strip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    decisions_dir = args.root / DECISIONS_DIR_RELPATH
    index_path = args.root / INDEX_RELPATH
    new_content = render_index(decisions_dir)

    if args.check:
        current = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        if current == new_content:
            print("docs/DECISIONS.md est a jour.")
            return 0
        print("docs/DECISIONS.md est perime -- relancer avec --apply.")
        return 1

    index_path.write_text(new_content, encoding="utf-8", newline="\n")
    print(f"docs/DECISIONS.md regenere ({len(load_adrs(decisions_dir))} decision(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
