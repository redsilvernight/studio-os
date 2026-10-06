"""P00 baseline (roadmap « vault serveur ») — chiffre l'écart de numérotation
entre les ADR fichiers de `docs/decisions/` et les DEC enregistrées côté serveur.

Le côté serveur n'est jamais interrogé par ce script : il lit un **snapshot
figé** et versionné (`docs/DEC_BASELINE_P00.json`), produit en lecture seule via
l'outil MCP `studio_get_decisions`. Le rapport humain
(`docs/DEC_BASELINE_P00.md`) est, lui, régénéré depuis les fichiers + le
snapshot : mêmes entrées, mêmes octets.

Un ADR fichier porte son identifiant soit dans `id` (fichiers `DEC-XXXX-*.md`),
soit dans `server_readable_id` (fichiers nommés autrement, p. ex. `DU0-A-*` ou
`AIB-P9-*`) — les deux sont reconnus, jamais devinés.

Usage:
    uv run python -m scripts.dec_baseline --root . --check   # exit 1 si périmé
    uv run python -m scripts.dec_baseline --root . --apply   # (ré)écrit le rapport
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from .adr_common import parse_adr_markdown

DECISIONS_DIR_RELPATH = "docs/decisions"
SNAPSHOT_RELPATH = "docs/DEC_BASELINE_P00.json"
REPORT_RELPATH = "docs/DEC_BASELINE_P00.md"
PREAMBLE_FILENAME = "_preamble.md"

SNAPSHOT_FORMAT = "studio.dec-baseline.server-snapshot/v1"
REPORT_FORMAT = "studio.dec-baseline.report/v1"

_DEC_RE = re.compile(r"^DEC-(\d{4})$")
_DEC_FILE_RE = re.compile(r"^DEC-\d{4}-")


def _dec_num(dec_id: str) -> int:
    return int(dec_id.split("-", 1)[1])


def _dec_id(number: int) -> str:
    return f"DEC-{number:04d}"


def _sorted_ids(ids: list[str] | set[str]) -> list[str]:
    return sorted(set(ids), key=_dec_num)


def _gaps(ids: list[str] | set[str]) -> list[str]:
    if not ids:
        return []
    numbers = sorted({_dec_num(i) for i in ids})
    present = set(numbers)
    return [_dec_id(n) for n in range(numbers[0], numbers[-1] + 1) if n not in present]


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


def load_file_decisions(
    decisions_dir: Path,
) -> tuple[dict[str, list[str]], list[str], dict[str, str]]:
    """Indexe les ADR fichiers par identifiant DEC.

    Retourne `(dec_id -> [noms de fichiers], adrs_sans_id, filename_mismatch)`.
    Un même DEC-id peut apparaître dans plusieurs fichiers : c'est un doublon,
    signalé mais jamais écrasé.
    """
    by_id: dict[str, list[str]] = {}
    unmapped: list[str] = []
    mismatch: dict[str, str] = {}
    if not decisions_dir.exists():
        return by_id, unmapped, mismatch
    for path in sorted(decisions_dir.glob("*.md")):
        if path.name == PREAMBLE_FILENAME:
            continue
        fields, _body = parse_adr_markdown(path.read_text(encoding="utf-8"))
        local_id = next(
            (
                value
                for value in (fields.get("id"), fields.get("server_readable_id"))
                if isinstance(value, str) and _DEC_RE.match(value)
            ),
            None,
        )
        if local_id is None:
            unmapped.append(path.name)
            continue
        by_id.setdefault(local_id, []).append(path.name)
        if _DEC_FILE_RE.match(path.name):
            filename_id = _dec_id(int(path.name.split("-", 2)[1]))
            if fields.get("id") != filename_id:
                mismatch[path.name] = str(fields.get("id"))
    return by_id, unmapped, mismatch


def load_snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != SNAPSHOT_FORMAT:
        raise ValueError(f"{path}: format de snapshot inattendu: {data.get('format')!r}")
    entries = data.get("decisions")
    if not isinstance(entries, list):
        raise ValueError(f"{path}: 'decisions' doit être une liste")
    return data


def _server_ids(snapshot: dict[str, Any], *, project_id: str | None = None) -> list[str]:
    ids: list[str] = []
    for entry in snapshot["decisions"]:
        dec_id = entry.get("readable_id")
        if not isinstance(dec_id, str) or not _DEC_RE.match(dec_id):
            continue
        if project_id is not None and entry.get("project_id") != project_id:
            continue
        ids.append(dec_id)
    return _sorted_ids(ids)


def _duplicates(ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for dec_id in ids:
        counts[dec_id] = counts.get(dec_id, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: _dec_num(kv[0]))
    return {dec_id: count for dec_id, count in ordered if count > 1}


def build_report(root: Path) -> dict[str, Any]:
    decisions_dir = root / DECISIONS_DIR_RELPATH
    snapshot_path = root / SNAPSHOT_RELPATH
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot = load_snapshot(snapshot_path)
    project_id = snapshot.get("project_scope_id")

    by_id, unmapped, mismatch = load_file_decisions(decisions_dir)
    file_ids = _sorted_ids(by_id.keys())
    dec_named = [name for names in by_id.values() for name in names if _DEC_FILE_RE.match(name)]
    renamed = sorted(
        (
            [dec_id, name]
            for dec_id, names in by_id.items()
            for name in names
            if not _DEC_FILE_RE.match(name)
        ),
        key=lambda pair: _dec_num(pair[0]),
    )

    server_all = _server_ids(snapshot)
    server_project = _server_ids(snapshot, project_id=project_id)
    server_ids = set(server_all)
    project_ids = set(server_project)
    file_id_set = set(file_ids)

    out_of_scope = _sorted_ids(server_ids - project_ids)

    return {
        "format": REPORT_FORMAT,
        "snapshot": {
            "path": SNAPSHOT_RELPATH,
            "format": snapshot.get("format"),
            "source": snapshot.get("source"),
            "project_scope_id": project_id,
            "sha256": "sha256:" + hashlib.sha256(snapshot_bytes).hexdigest(),
            "entries": len(snapshot["decisions"]),
        },
        "files": {
            "adr_files": sum(len(names) for names in by_id.values()) + len(unmapped),
            "dec_named": len(dec_named),
            "dec_ids": len(file_ids),
            "min": _dec_num(file_ids[0]) if file_ids else None,
            "max": _dec_num(file_ids[-1]) if file_ids else None,
            "gaps": _gaps(file_ids),
            "duplicates": {dec_id: names for dec_id, names in by_id.items() if len(names) > 1},
            "unmapped": unmapped,
            "renamed": renamed,
            "filename_mismatch": mismatch,
        },
        "server": {
            "all": {
                "count": len(server_all),
                "min": _dec_num(server_all[0]) if server_all else None,
                "max": _dec_num(server_all[-1]) if server_all else None,
                "gaps": _gaps(server_all),
                "duplicates": _duplicates(server_all),
            },
            "project": {
                "count": len(server_project),
                "min": _dec_num(server_project[0]) if server_project else None,
                "max": _dec_num(server_project[-1]) if server_project else None,
                "gaps": _gaps(server_project),
            },
            "out_of_scope": {"count": len(out_of_scope), "ids": out_of_scope},
        },
        "delta": {
            "global": {
                "file_only": _sorted_ids(file_id_set - server_ids),
                "server_only": _sorted_ids(server_ids - file_id_set),
            },
            "project": {
                "file_only": _sorted_ids(file_id_set - project_ids),
                "server_only": _sorted_ids(project_ids - file_id_set),
            },
        },
    }


def _ids_cell(ids: list[str]) -> str:
    return ", ".join(f"`{i}`" for i in ids) if ids else "—"


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    files = report["files"]
    server = report["server"]
    delta = report["delta"]
    snapshot = report["snapshot"]

    parts: list[str] = []
    parts.append("# Baseline P00 — numérotation des DEC (fichiers vs serveur)\n")
    parts.append(
        "Rapport chiffré et reproductible de l'écart de numérotation entre les ADR\n"
        "fichiers de `docs/decisions/` et les DEC enregistrées côté serveur. Le côté\n"
        f"serveur est un snapshot figé (`{SNAPSHOT_RELPATH}`), lu via l'outil MCP\n"
        "`studio_get_decisions` (lecture seule).\n"
    )
    parts.append(
        "Reproduire / vérifier ce rapport :\n\n"
        "```\n"
        "uv run python -m scripts.dec_baseline --root . --check\n"
        "uv run python -m scripts.dec_baseline --root . --apply\n"
        "```\n"
    )
    parts.append("## Snapshot serveur\n")
    parts.append(
        f"- Source : `{snapshot['source']}`\n"
        f"- Format : `{snapshot['format']}`\n"
        f"- Portée projet : `{snapshot['project_scope_id']}`\n"
        f"- Entrées : {snapshot['entries']}\n"
        f"- Empreinte : `{snapshot['sha256']}`\n"
    )
    parts.append("## Fichiers `docs/decisions/`\n")
    parts.append(
        f"- ADR fichiers : **{files['adr_files']}** "
        f"({files['dec_named']} nommés `DEC-XXXX-*.md`, "
        f"{files['adr_files'] - files['dec_named']} nommés autrement)\n"
        f"- Identifiants DEC couverts : **{files['dec_ids']}**\n"
        f"- Numéro max : **{files['max']}** (min {files['min']})\n"
        f"- Trous : **{len(files['gaps'])}**\n"
        f"- Doublons : **{len(files['duplicates'])}**\n"
        f"- ADR sans identifiant DEC : **{len(files['unmapped'])}**\n"
        f"- Discordance fichier/front matter : **{len(files['filename_mismatch'])}**\n"
    )
    if files["renamed"]:
        parts.append("### ADR nommés autrement (identifiant via `server_readable_id`)\n")
        parts.append(
            "Ces ADR ne suivent pas le motif `DEC-XXXX-*.md` mais portent leur\n"
            "identifiant DEC dans `server_readable_id` : ils comptent comme\n"
            "correspondances fichiers ↔ serveur.\n"
        )
        parts.append("".join(f"- `{name}` → `{dec_id}`\n" for dec_id, name in files["renamed"]))
    rows = [
        [
            "Numéro max",
            str(files["max"]),
            str(server["all"]["max"]),
            str(server["project"]["max"]),
        ],
        [
            "Nombre de DEC",
            str(files["dec_ids"]),
            str(server["all"]["count"]),
            str(server["project"]["count"]),
        ],
        [
            "Trous",
            str(len(files["gaps"])),
            str(len(server["all"]["gaps"])),
            str(len(server["project"]["gaps"])),
        ],
        [
            "Doublons",
            str(len(files["duplicates"])),
            str(len(server["all"]["duplicates"])),
            "—",
        ],
    ]
    parts.append("## Chiffres\n")
    parts.append(
        "\n".join(_table(["Métrique", "Fichiers", "Serveur (global)", "Serveur (projet)"], rows))
    )
    parts.append("\n")
    parts.append("## Trous de numérotation\n")
    parts.append(f"- Fichiers : {_ids_cell(files['gaps'])}\n")
    parts.append(f"- Serveur global : {_ids_cell(server['all']['gaps'])}\n")
    parts.append(f"- Serveur projet : {_ids_cell(server['project']['gaps'])}\n")
    parts.append("## Écart fichiers ↔ serveur\n")
    parts.append("### Portée globale (toutes les DEC serveur)\n")
    parts.append(f"- Présents en fichier seulement : {_ids_cell(delta['global']['file_only'])}\n")
    parts.append(f"- Présents au serveur seulement : {_ids_cell(delta['global']['server_only'])}\n")
    parts.append("### Portée projet (`project_scope_id`)\n")
    parts.append(f"- Présents en fichier seulement : {_ids_cell(delta['project']['file_only'])}\n")
    parts.append(
        f"- Présents au serveur seulement : {_ids_cell(delta['project']['server_only'])}\n"
    )
    parts.append(
        f"- DEC serveur hors portée projet (project_id null ou autre) : "
        f"{server['out_of_scope']['count']} — {_ids_cell(server['out_of_scope']['ids'])}\n"
    )
    if files["duplicates"]:
        parts.append("## Doublons (fichiers)\n")
        for dec_id, names in files["duplicates"].items():
            parts.append(f"- `{dec_id}` : {', '.join(f'`{n}`' for n in names)}\n")
    if files["unmapped"]:
        parts.append("## ADR sans identifiant DEC\n")
        parts.append("".join(f"- `{name}`\n" for name in files["unmapped"]))
    if files["filename_mismatch"]:
        parts.append("## Discordances nom de fichier / front matter\n")
        for name, front_id in files["filename_mismatch"].items():
            parts.append(f"- `{name}` : `id: {front_id}`\n")
    return "\n".join(part.rstrip("\n") for part in parts).strip() + "\n"


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 si le rapport est périmé")
    mode.add_argument("--apply", action="store_true", help="(ré)écrit le rapport")
    parser.add_argument("--stdout", action="store_true", help="imprime aussi le rapport")
    args = parser.parse_args()

    report = build_report(args.root)
    rendered = render_markdown(report)
    target = args.root / REPORT_RELPATH
    if args.stdout:
        sys.stdout.buffer.write(rendered.encode("utf-8"))
        sys.stdout.buffer.flush()
    if args.apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"{REPORT_RELPATH} régénéré.")
        return 0
    current = target.read_text(encoding="utf-8") if target.is_file() else ""
    if _normalize(current) != rendered:
        print(f"{REPORT_RELPATH} est périmé -- relancer avec --apply.")
        return 1
    print(f"{REPORT_RELPATH} est à jour.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
