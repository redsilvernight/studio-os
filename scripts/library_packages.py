"""Build and verify the Core / Project / Personal Library package manifests.

Sources never move: Core and Project manifests point at tracked files
(`.agents/`, `library/`); Personal copies its sources into the git-ignored
`library/packages/personal/content/`. Output is deterministic (no timestamp).

    python scripts/library_packages.py build   # write manifests + CATALOG.md
    python scripts/library_packages.py check   # verify, exit 1 on any problem
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import yaml

SCHEMA = "studio.library.package/v1"
LAYERS = ("core", "project", "personal")
# A layer may depend on itself and on the layers below it.
ALLOWED_DEPS = {"core": {"core"}, "project": {"core", "project"}, "personal": {"core", "personal"}}
OWNER = {"core": "studio", "project": "project", "personal": "user:self"}
VISIBILITY = {"core": "public", "project": "project", "personal": "private"}
KINDS = {"rule", "skill", "hook", "agent_definition", "model_profile", "workflow"}
DECISIONS = {
    "CORE_PUBLIC",
    "PERSONAL_PRIVATE",
    "PROJECT_SPECIFIC",
    "EXCLUDED_DUPLICATE",
    "EXCLUDED_OBSOLETE",
    "NOT_READY",
    "NOT_PUBLISHABLE",
}
DEST = {"CORE_PUBLIC": "core", "PERSONAL_PRIVATE": "personal", "PROJECT_SPECIFIC": "project"}
SKIP_NAMES = {"__pycache__"}

# Personal-environment markers: forbidden in the tracked (Core/Project) layers.
PERSONAL_RE = re.compile(
    r"[A-Za-z]:\\|/Users/|/home/\w|redsi|LocalAI|local-ai-hub|obsidian-memory|AI-Memory"
    r"|opencode-dispatch|FLO-LAPTOP|bonsai",
    re.I,
)
SECRET_RE = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE"
    r"|xox[bp]-[0-9A-Za-z-]{10,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.|(?i:bearer)\s+[A-Za-z0-9._-]{24,}"
)
HOOK_COMPAT = {"claude-code": "supported", "opencode": "supported", "codex": "unverified"}
FULL_COMPAT = {"claude-code": "supported", "opencode": "supported", "codex": "supported"}
PERSONAL_COMPAT = {"claude-code": "supported", "opencode": "unverified", "codex": "unverified"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def personal_home() -> Path:
    return Path(os.environ.get("STUDIO_PERSONAL_HOME") or Path.home() / ".claude")


def frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    data = yaml.safe_load(text[3:end])
    return data if isinstance(data, dict) else {}


def _files(base: Path) -> list[Path]:
    if base.is_file():
        return [base]
    return sorted(p for p in base.rglob("*") if p.is_file() and not (set(p.parts) & SKIP_NAMES))


def resolve_source(source: str, root: Path, home: Path) -> Path:
    """`home:` → personal home, `private:` → git-ignored private sources."""
    if source.startswith("home:"):
        return home / source[5:]
    if source.startswith("private:"):
        return root / "library/private/personal" / source[8:]
    return root / source


def source_files(spec: dict, root: Path, home: Path) -> list[Path]:
    """Files of one entry; a hook is its `.md` plus its sibling scripts."""
    base = resolve_source(spec["source"], root, home)
    if spec["kind"] == "hook" and spec["source"].startswith("library/"):
        return sorted(p for p in base.parent.glob(f"{base.name}.*") if p.is_file())
    return _files(base) if base.exists() else []


def primary_meta(spec: dict, files: list[Path]) -> dict:
    main = next((p for p in files if p.name in (f"{spec['key']}.md", "SKILL.md")), None)
    if main is None and files:
        main = next((p for p in files if p.suffix == ".md"), files[0])
    return frontmatter(main.read_text(encoding="utf-8")) if main else {}


def raw_deps(spec: dict, meta: dict) -> list[tuple[str, str]]:
    kind, out = spec["kind"], []
    if kind == "agent_definition":
        out += [("rule", k) for k in meta.get("rules") or []]
        out += [("skill", k) for k in meta.get("skills") or []]
        if meta.get("model_profile"):
            out.append(("model_profile", meta["model_profile"]))
    elif kind == "workflow":
        out += [("agent_definition", p["agent_stable_key"]) for p in meta.get("participants") or []]
    return sorted(set(out))


def scan(files: list[Path]) -> list[str]:
    """Reasons a tracked-layer file must not ship; empty when clean."""
    problems = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path.name}: binaire")
            continue
        if SECRET_RE.search(text):
            problems.append(f"{path.name}: secret évident")
        if PERSONAL_RE.search(text):
            problems.append(f"{path.name}: référence personnelle")
    return problems


def load_decisions(root: Path) -> list[dict]:
    path = root / "library/packages/decisions.json"
    return json.loads(path.read_text(encoding="utf-8"))


def build_entries(root: Path, home: Path, decisions: list[dict]) -> tuple[dict, list[dict]]:
    """Return ({layer: [entry]}, effective decisions). A decision that cannot be
    honoured (missing source, secret, personal reference in a tracked layer) is
    demoted to NOT_READY with the reason — never shipped, never invented."""
    packages: dict[str, list[dict]] = {layer: [] for layer in LAYERS}
    effective: list[dict] = []
    for spec in decisions:
        spec = dict(spec)
        layer = DEST.get(spec["decision"])
        if layer:
            files = source_files(spec, root, home)
            reason = None
            if not files:
                reason = "source introuvable"
            elif layer != "personal":
                found = scan(files)
                reason = "; ".join(found) if found else None
            if reason:
                spec["decision"], spec["rationale"] = "NOT_READY", f"{spec['rationale']} [{reason}]"
                spec["destination"] = None
            else:
                packages[layer].append(make_entry(spec, layer, files, root, home))
        effective.append(spec)
    for entries in packages.values():
        entries.sort(key=lambda e: (e["kind"], e["stable_key"]))
    return packages, effective


def make_entry(spec: dict, layer: str, files: list[Path], root: Path, home: Path) -> dict:
    meta = primary_meta(spec, files)
    base = resolve_source(spec["source"], root, home)
    anchor = base if base.is_dir() else base.parent
    if layer == "personal":
        rel_dir = f"content/{spec['kind']}/{spec['key']}"
        listing = [
            {
                "path": f"{rel_dir}/{p.relative_to(anchor).as_posix()}",
                "sha256": sha256(p.read_bytes()),
            }
            for p in files
        ]
        sources = {f["path"]: p for f, p in zip(listing, files, strict=True)}
        source_ref = spec["source"].split(":", 1)[0] + ":" + spec["kind"] + "/" + spec["key"]
    else:
        listing = [
            {"path": p.relative_to(root).as_posix(), "sha256": sha256(p.read_bytes())}
            for p in files
        ]
        sources, source_ref = {}, spec["source"]
    digest = sha256("\n".join(f"{f['path']}:{f['sha256']}" for f in listing).encode())
    compat = (
        PERSONAL_COMPAT
        if layer == "personal"
        else (HOOK_COMPAT if spec["kind"] == "hook" else FULL_COMPAT)
    )
    entry = {
        "stable_key": spec["key"],
        "kind": spec["kind"],
        "scope": {"core": "studio", "project": "project", "personal": "user"}[layer],
        "owner": OWNER[layer],
        "version": spec["version"],
        "tier": spec["tier"],
        "source": source_ref,
        "files": listing,
        "sha256": digest,
        "dependencies": [{"kind": k, "stable_key": s} for k, s in raw_deps(spec, meta)],
        "compatibility": compat,
        "requires_consent": spec["kind"] == "hook",
        "visibility": VISIBILITY[layer],
        "status": "ready",
        "supersedes": spec.get("supersedes"),
    }
    entry["_sources"] = sources
    return entry


def manifest(layer: str, entries: list[dict]) -> dict:
    return {
        "schema": SCHEMA,
        "package": f"studios-{layer}",
        "layer": layer,
        "visibility": VISIBILITY[layer],
        "entries": [{k: v for k, v in e.items() if k != "_sources"} for e in entries],
    }


def dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def validate(manifests: dict[str, dict], base_dir: Path, root: Path) -> list[str]:
    """Structural checks over the three manifests; `base_dir` holds Personal."""
    errors: list[str] = []
    index: dict[tuple[str, str], str] = {}
    for layer, man in manifests.items():
        if man.get("schema") != SCHEMA or man.get("layer") != layer:
            errors.append(f"{layer}: schéma ou couche invalide")
        seen = set()
        for e in man["entries"]:
            ident = (e["kind"], e["stable_key"])
            where = f"{layer}/{e['kind']}/{e['stable_key']}"
            if e["kind"] not in KINDS:
                errors.append(f"{where}: kind inconnu")
            if ident in seen:
                errors.append(f"{where}: clé dupliquée dans le package")
            seen.add(ident)
            if layer != "personal":
                index.setdefault(ident, layer)
            if e["owner"] != OWNER[layer] or e["visibility"] != VISIBILITY[layer]:
                errors.append(f"{where}: owner/visibilité incohérents avec la couche")
            if not isinstance(e["version"], int) or e["version"] < 1:
                errors.append(f"{where}: version invalide")
            if not e["files"]:
                errors.append(f"{where}: aucun contenu")
            for f in e["files"]:
                path = (base_dir if layer == "personal" else root) / f["path"]
                if not path.is_file():
                    errors.append(f"{where}: fichier absent {f['path']}")
                elif sha256(path.read_bytes()) != f["sha256"]:
                    errors.append(f"{where}: hash différent {f['path']}")
                elif layer != "personal" and (scan([path])):
                    errors.append(f"{where}: fuite détectée {f['path']}")
            digest = sha256("\n".join(f"{f['path']}:{f['sha256']}" for f in e["files"]).encode())
            if digest != e["sha256"]:
                errors.append(f"{where}: hash d'entrée incohérent")
    core_keys = {i for i, layer in index.items() if layer == "core"}
    project_keys = {i for i, layer in index.items() if layer == "project"}
    for clash in sorted(core_keys & project_keys):
        errors.append(f"collision Core/Project: {clash[0]}/{clash[1]}")
    available = {
        layer: {(e["kind"], e["stable_key"]) for e in man["entries"]}
        for layer, man in manifests.items()
    }
    graph: dict[tuple[str, tuple[str, str]], list[tuple[str, tuple[str, str]]]] = {}
    for layer, man in manifests.items():
        for e in man["entries"]:
            node = (layer, (e["kind"], e["stable_key"]))
            graph[node] = []
            for d in e["dependencies"]:
                target = (d["kind"], d["stable_key"])
                owner = next(
                    (x for x in ALLOWED_DEPS[layer] if target in available.get(x, ())), None
                )
                if owner is None:
                    errors.append(
                        f"{layer}/{e['kind']}/{e['stable_key']}: dépendance non résolue {target}"
                    )
                else:
                    graph[node].append((owner, target))
    visiting: set = set()
    done: set = set()

    def visit(node: tuple) -> bool:
        if node in done:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        cyclic = any(visit(n) for n in graph.get(node, ()))
        visiting.discard(node)
        done.add(node)
        return cyclic

    for node in sorted(graph):
        if visit(node):
            errors.append(f"cycle de dépendances via {node[1][1]}")
            break
    return errors


def render_catalog(effective: list[dict], packages: dict) -> str:
    counts: dict[str, int] = {}
    for d in effective:
        counts[d["decision"]] = counts.get(d["decision"], 0) + 1
    lines = [
        "# Catalogue canonique Library (Phase 2C)",
        "",
        "Généré par `scripts/library_packages.py build` à partir de "
        "`library/packages/decisions.json`. Une décision qui ne peut pas être honorée "
        "(source absente, secret, référence personnelle dans une couche suivie) est "
        "rétrogradée `NOT_READY` avec la raison. Les versions sont celles de la rebuild : "
        "`active+1` quand la source canonique remplace une version historique.",
        "",
        "## Synthèse",
        "",
        "| Décision | Nombre |",
        "|---|---:|",
    ]
    lines += [f"| {k} | {v} |" for k, v in sorted(counts.items())]
    lines += ["", "| Package | Entrées prêtes |", "|---|---:|"]
    lines += [f"| {k} | {len(v)} |" for k, v in packages.items()]
    lines += [
        "",
        "## Décisions",
        "",
        "| Origine | Type | Clé | Version | Décision | Destination | Source | Justification |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for d in sorted(effective, key=lambda d: (d["scope"], d["kind"], d["key"])):
        origin = d["scope"] + (" (nouveau)" if d["new"] else "")
        src = d["source"].split(":", 1)[0] + ":…" if ":" in d["source"] else d["source"]
        extra = f" Remplace {d['supersedes']}." if d.get("supersedes") else ""
        lines.append(
            f"| {origin} | {d['kind']} | `{d['key']}` | {d['version']} | {d['decision']} "
            f"| {d['destination'] or '—'} | `{src}` | {d['rationale']}{extra} |"
        )
    return "\n".join(lines) + "\n"


def build(root: Path, home: Path) -> dict:
    packages, effective = build_entries(root, home, load_decisions(root))
    out = root / "library/packages"
    personal = out / "personal"
    if personal.exists():
        shutil.rmtree(personal)
    for layer in LAYERS:
        (out / layer).mkdir(parents=True, exist_ok=True)
    for e in packages["personal"]:
        for rel, src in e["_sources"].items():
            target = personal / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
    for layer in LAYERS:
        (out / layer / "manifest.json").write_text(
            dump(manifest(layer, packages[layer])), encoding="utf-8", newline="\n"
        )
    (out / "decisions.effective.json").write_text(dump(effective), encoding="utf-8", newline="\n")
    catalog = root / "docs/library/rebuild-2026/CATALOG.md"
    catalog.write_text(render_catalog(effective, packages), encoding="utf-8", newline="\n")
    return packages


def check(root: Path) -> list[str]:
    out = root / "library/packages"
    manifests = {}
    for layer in LAYERS:
        path = out / layer / "manifest.json"
        if not path.is_file():
            return [f"manifeste absent: {layer}"]
        manifests[layer] = json.loads(path.read_text(encoding="utf-8"))
    return validate(manifests, out / "personal", root)


def main(argv: list[str]) -> int:
    root, home = repo_root(), personal_home()
    if argv[:1] == ["build"]:
        packages = build(root, home)
        print({k: len(v) for k, v in packages.items()})
    errors = check(root)
    for e in errors:
        print("ERREUR", e)
    print("OK" if not errors else f"{len(errors)} erreur(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
