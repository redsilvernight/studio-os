"""Import the Core / Project / Personal package manifests through the Library API.

Never writes to the database: every write is an authenticated call of the
official client (`studio_client.publish`), so scopes, owners, roles, content
schemas and pin rules are the server's own. The caller decides the principal:
Core (studio scope) needs the admin role, Project a project writer, Personal its owner.

    uv run python scripts/library_import.py check          # offline: hashes + schemas
    uv run python scripts/library_import.py import --layer core --api-url URL \
        --token-env VAR [--project-id UUID] [--no-activate] [--dry-run]

Not transactional across entries (the API has no batch): an entry that fails stops the
run; entries already published stay, and a rerun skips them (`unchanged`). Recovery =
fix the cause, rerun the same command.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import library_packages as lp  # noqa: E402
from studio_client.api_client import StudioApiClient  # noqa: E402
from studio_client.publish import (  # noqa: E402
    _LIBRARY_KIND,
    PublishError,
    PublishItem,
    PublishResult,
    _find_resource,
    _publish_one,
)
from studio_contracts.library import (  # noqa: E402
    RULE_SKILL_TEXT_MAX_LENGTH,
    SKILL_FILE_TEXT_MAX_LENGTH,
    SKILL_FILES_MAX,
    SKILL_FILES_TOTAL_MAX_LENGTH,
    DependencyPin,
    LibraryKind,
    LibraryScope,
    ResourceDependencyPin,
    content_validation_errors,
)

SCOPE = {
    "core": LibraryScope.STUDIO,
    "project": LibraryScope.PROJECT,
    "personal": LibraryScope.USER,
}
KIND_ALIAS = {"agent_definition": "agent"}  # manifest kind -> PublishKind
_MARKER_RE = re.compile(r"^<!-- studio-os-library:.*?-->\n*", re.M)
_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.S)
SKILL_TEXT_MAX = RULE_SKILL_TEXT_MAX_LENGTH


def _check_skill_files(key: str, files: dict[str, str]) -> None:
    """Same limits as the server contract, reported before any API call."""
    if len(files) > SKILL_FILES_MAX:
        raise ImportErrorReport(f"skill {key}: {len(files)} auxiliary files, max {SKILL_FILES_MAX}")
    for path, text in files.items():
        if len(text) > SKILL_FILE_TEXT_MAX_LENGTH:
            raise ImportErrorReport(
                f"skill {key}: {path} exceeds {SKILL_FILE_TEXT_MAX_LENGTH} chars"
            )
    if sum(len(text) for text in files.values()) > SKILL_FILES_TOTAL_MAX_LENGTH:
        raise ImportErrorReport(
            f"skill {key}: auxiliary files exceed {SKILL_FILES_TOTAL_MAX_LENGTH} chars in total"
        )


class ImportErrorReport(Exception):
    """A package that must not be imported (hash, schema, dependency)."""


@dataclass
class LayerPlan:
    layer: str
    items: list[PublishItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _layer_dir(layer: str, root: Path) -> Path:
    return root / "library/packages" / layer


def _read(base: Path, rel: str, expected: str) -> str:
    path = base / rel
    data = path.read_bytes()
    if lp.sha256(data) != expected:
        raise ImportErrorReport(f"hash mismatch: {rel}")
    return data.decode("utf-8").replace("\r\n", "\n")


def _split(text: str) -> tuple[dict[str, Any], str]:
    match = _FM_RE.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    return (meta if isinstance(meta, dict) else {}), _MARKER_RE.sub(
        "", match.group(2)
    ).strip() + "\n"


def _content(entry: dict[str, Any], texts: dict[str, str]) -> tuple[str, dict[str, Any], list[str]]:
    """(title, Library content, warnings) of one entry, from its verified files."""
    key, kind = entry["stable_key"], entry["kind"]
    named = [p for p in texts if Path(p).name in (f"{key}.md", "SKILL.md")]
    main = min(named, key=lambda p: (p.count("/"), p), default=None)
    main = main or next(p for p in texts if p.endswith(".md"))
    meta, body = _split(texts[main])
    warnings: list[str] = []
    title = str(meta.get("description") or meta.get("summary") or key)
    title = " ".join(title.split())
    if kind in ("rule", "skill"):
        if len(body) > SKILL_TEXT_MAX:
            raise ImportErrorReport(f"{kind} {key}: text exceeds {SKILL_TEXT_MAX} chars")
        content: dict[str, Any] = {"content_schema": f"studio.library.{kind}/v1", "text": body}
        if kind == "skill" and len(texts) > 1:
            root = main.rsplit("/", 1)[0] + "/"
            aux = {
                path.removeprefix(root): text
                for path, text in sorted(texts.items())
                if path != main
            }
            _check_skill_files(key, aux)
            content["files"] = [
                {"path": path, "text": text, "sha256": lp.sha256(text.encode("utf-8"))}
                for path, text in aux.items()
            ]
        elif len(texts) > 1:
            warnings.append(f"{kind} {key}: {len(texts) - 1} auxiliary file(s) not stored")
        return (key if kind == "rule" else title), content, warnings
    if kind == "agent_definition":
        summary = str(meta.get("summary") or meta.get("description") or key)
        return (
            key,
            {
                "content_schema": "studio.library.agent_definition/v1",
                "summary": " ".join(summary.split()),
                "intended_use": body,
            },
            warnings,
        )
    if kind == "model_profile":
        return (
            key,
            {
                "content_schema": "studio.library.model_profile/v1",
                "requirements": meta.get("requirements") or {},
                "description": meta.get("description"),
            },
            warnings,
        )
    if kind == "workflow":
        return (
            key,
            {
                "content_schema": "studio.library.workflow/v1",
                "summary": meta.get("summary"),
                "participants": meta.get("participants") or [],
                "inputs": meta.get("inputs") or [],
                "outputs": meta.get("outputs") or [],
            },
            warnings,
        )
    if kind == "hook":
        scripts = []
        for script in meta.get("scripts") or []:
            rel = next((p for p in texts if Path(p).name == script["file"]), None)
            if rel is None:
                raise ImportErrorReport(f"hook {key}: script {script['file']} missing")
            scripts.append(
                {"os": script.get("os", "any"), "shell": script["shell"], "body": texts[rel]}
            )
        return (
            key,
            {
                "content_schema": "studio.library.hook/v1",
                "event": meta["event"],
                "matcher": meta.get("matcher"),
                "mode": meta.get("mode", "advisory"),
                "timeout_seconds": meta.get("timeout_seconds", 30),
                "scripts": scripts,
                "description": meta.get("description"),
            },
            warnings,
        )
    raise ImportErrorReport(f"unsupported kind {kind}")


def _topo(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dependencies first; a cycle or a self-layer dependency left unresolved raises."""
    by_id = {(e["kind"], e["stable_key"]): e for e in entries}
    done: dict[tuple[str, str], bool] = {}
    out: list[dict[str, Any]] = []

    def visit(entry: dict[str, Any], trail: tuple[tuple[str, str], ...]) -> None:
        ident = (entry["kind"], entry["stable_key"])
        if done.get(ident):
            return
        if ident in trail:
            raise ImportErrorReport(f"dependency cycle: {ident}")
        for dep in entry["dependencies"]:
            target = by_id.get((dep["kind"], dep["stable_key"]))
            if target is not None:
                visit(target, (*trail, ident))
        done[ident] = True
        out.append(entry)

    for entry in entries:
        visit(entry, ())
    return out


def load_plan(layer: str, root: Path = ROOT) -> LayerPlan:
    """Read, verify (file + entry hashes, content schemas) and order one package.

    Offline, deterministic, no network. Raises on the first inconsistency."""
    base = _layer_dir(layer, root)
    manifest = json.loads((base / "manifest.json").read_text("utf-8"))
    if manifest["schema"] != lp.SCHEMA or manifest["layer"] != layer:
        raise ImportErrorReport(f"{layer}: unexpected manifest header")
    plan = LayerPlan(layer)
    # Tracked layers address files from the repo root; Personal from its own directory.
    file_base = base if layer == "personal" else root
    for entry in _topo([e for e in manifest["entries"] if e["status"] == "ready"]):
        if entry["scope"] != SCOPE[layer].value or entry["visibility"] != lp.VISIBILITY[layer]:
            raise ImportErrorReport(
                f"{entry['stable_key']}: scope/visibility differs from layer {layer}"
            )
        digest = lp.sha256("\n".join(f"{f['path']}:{f['sha256']}" for f in entry["files"]).encode())
        if digest != entry["sha256"]:
            raise ImportErrorReport(f"{entry['stable_key']}: entry hash mismatch")
        texts = {f["path"]: _read(file_base, f["path"], f["sha256"]) for f in entry["files"]}
        title, content, warnings = _content(entry, texts)
        kind = LibraryKind(entry["kind"])
        errors = content_validation_errors(kind, content)
        if errors:
            raise ImportErrorReport(f"{entry['stable_key']}: invalid content {errors}")
        short = KIND_ALIAS.get(entry["kind"], entry["kind"])
        pins = tuple(
            (KIND_ALIAS.get(d["kind"], d["kind"]), d["stable_key"]) for d in entry["dependencies"]
        )
        plan.items.append(PublishItem(short, entry["stable_key"], title, content, pins))
        plan.warnings += warnings
    return plan


async def _pin(
    client: StudioApiClient,
    kind: str,
    key: str,
    scope: LibraryScope,
    project_id: UUID | None,
    published: dict[tuple[str, str], tuple[UUID, int]],
) -> ResourceDependencyPin:
    """Pin to the version this run published/kept, else to the active version of the
    same layer, then of Studio. Carries the resource id so a same-key resource of
    another scope can never make the pin ambiguous."""
    if (kind, key) in published:
        resource_id, version = published[(kind, key)]
        return ResourceDependencyPin(
            kind=_LIBRARY_KIND[kind], stable_key=key, version=version, resource_id=resource_id
        )
    lookups = [(scope, project_id)] + (
        [(LibraryScope.STUDIO, None)] if scope is not LibraryScope.STUDIO else []
    )
    for lookup_scope, lookup_project in lookups:
        found = await _find_resource(client, _LIBRARY_KIND[kind], key, lookup_scope, lookup_project)
        if found is not None and found.active_version > 0:
            return ResourceDependencyPin(
                kind=_LIBRARY_KIND[kind],
                stable_key=key,
                version=found.active_version,
                resource_id=found.id,
            )
    raise PublishError(f"{kind} {key!r}: dependency has no active version to pin")


async def import_plan(
    client: StudioApiClient,
    plan: LayerPlan,
    *,
    project_id: UUID | None = None,
    activate: bool = True,
    dry_run: bool = False,
) -> list[PublishResult]:
    """Publish one package in dependency order; stops at the first failure."""
    scope = SCOPE[plan.layer]
    if (scope is LibraryScope.PROJECT) != (project_id is not None):
        raise PublishError("project_id is required for, and only valid with, the project layer")
    published: dict[tuple[str, str], tuple[UUID, int]] = {}
    results: list[PublishResult] = []
    for item in plan.items:
        pins: list[DependencyPin] = [
            await _pin(client, k, s, scope, project_id, published) for k, s in item.pins
        ]
        result = await _publish_one(
            client,
            item,
            pins,
            scope=scope,
            project_id=project_id,
            activate=activate,
            dry_run=dry_run,
        )
        results.append(result)
        if not dry_run:
            resource = await _find_resource(
                client, _LIBRARY_KIND[item.kind], item.stable_key, scope, project_id
            )
            assert resource is not None
            published[(item.kind, item.stable_key)] = (resource.id, result.version)
    return results


def summarize(results: list[PublishResult]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for r in results:
        counts[r.action] += 1
        counts["activated"] += int(r.activated)
    return dict(counts)


def _main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    imp = sub.add_parser("import")
    imp.add_argument("--layer", choices=lp.LAYERS, required=True)
    imp.add_argument("--api-url", required=True)
    imp.add_argument("--token-env", required=True, help="env var holding the machine token")
    imp.add_argument("--project-id", type=UUID)
    imp.add_argument("--no-activate", action="store_true")
    imp.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.cmd == "check":
        total = 0
        for layer in lp.LAYERS:
            plan = load_plan(layer)
            total += len(plan.items)
            print(f"{layer}: {len(plan.items)} entries OK, {len(plan.warnings)} warning(s)")
            for w in plan.warnings:
                print(f"  warn: {w}")
        print(f"total {total}")
        return 0

    from studio_client.config import ClientConfig

    class _Token:
        def __init__(self, value: str) -> None:
            self.value = value

        def get_token(self, origin: str) -> str:
            return self.value

        def set_token(self, origin: str, token: str) -> None: ...

        def clear_token(self, origin: str) -> None: ...

    token = os.environ.get(args.token_env)
    if not token:
        print(f"env var {args.token_env} is empty", file=sys.stderr)
        return 2

    async def run() -> int:
        client = StudioApiClient(ClientConfig(api_base_url=args.api_url), _Token(token))
        results = await import_plan(
            client,
            load_plan(args.layer),
            project_id=args.project_id,
            activate=not args.no_activate,
            dry_run=args.dry_run,
        )
        print(json.dumps({"layer": args.layer, "results": summarize(results), "n": len(results)}))
        return 0

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(_main())
