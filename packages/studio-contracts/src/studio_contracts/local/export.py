from __future__ import annotations

import argparse
import importlib
import inspect
import json
import pkgutil
import sys
from pathlib import Path
from typing import Any

import studio_contracts.local as local_package
from studio_contracts.local.bridge import BRIDGE_COMMANDS, BRIDGE_EVENTS
from studio_contracts.local.common import LOCAL_PROTOCOL_LABEL, LocalContractModel
from studio_contracts.local.fixtures import build_fixtures, build_invalid_fixtures

EXPORT_DIRECTORY = Path("contracts") / "local"
EXPORT_SCHEMA_VERSION = 1
SKIPPED_MODULES = frozenset({"export", "fixtures"})


def model_registry() -> dict[str, type[LocalContractModel]]:
    registry: dict[str, type[LocalContractModel]] = {}
    for module_info in pkgutil.iter_modules(local_package.__path__):
        if module_info.name in SKIPPED_MODULES:
            continue
        module = importlib.import_module(f"{local_package.__name__}.{module_info.name}")
        for name, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(candidate, LocalContractModel)
                and candidate is not LocalContractModel
                and candidate.__module__ == module.__name__
                and not name.startswith("_")
            ):
                registry[name] = candidate
    return registry


def _dump_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_allowlist() -> dict[str, Any]:
    commands = [
        {
            "command": spec.command.value,
            "request": spec.request.__name__,
            "response": spec.response.__name__,
            "capability": spec.capability,
            "mutating": spec.mutating,
            "cancellable": spec.cancellable,
            "timeout_ms": spec.timeout_ms,
            "max_request_bytes": spec.max_request_bytes,
            "max_response_bytes": spec.max_response_bytes,
        }
        for spec in sorted(BRIDGE_COMMANDS.values(), key=lambda s: s.command.value)
    ]
    events = [
        {"event": name.value, "payload": model.__name__}
        for name, model in sorted(BRIDGE_EVENTS.items(), key=lambda item: item[0].value)
    ]
    return {
        "protocol": LOCAL_PROTOCOL_LABEL,
        "schema_version": EXPORT_SCHEMA_VERSION,
        "commands": commands,
        "events": events,
    }


def build_export() -> dict[str, str]:
    files: dict[str, str] = {}
    registry = model_registry()
    for name, model in sorted(registry.items()):
        files[f"schemas/{name}.json"] = _dump_json(model.model_json_schema())

    manifest_fixtures: list[dict[str, str]] = []
    for fixture in build_fixtures():
        files[f"fixtures/valid/{fixture.name}.json"] = _dump_json(
            {"model": fixture.model_name, "data": fixture.model.model_dump(mode="json")}
        )
        manifest_fixtures.append({"name": fixture.name, "model": fixture.model_name})

    manifest_invalid: list[dict[str, str]] = []
    for invalid in build_invalid_fixtures():
        files[f"fixtures/invalid/{invalid.name}.json"] = _dump_json(
            {"model": invalid.model_name, "data": invalid.data, "reason": invalid.reason}
        )
        manifest_invalid.append(
            {"name": invalid.name, "model": invalid.model_name, "reason": invalid.reason}
        )

    files["allowlist.json"] = _dump_json(build_allowlist())
    files["manifest.json"] = _dump_json(
        {
            "protocol": LOCAL_PROTOCOL_LABEL,
            "schema_version": EXPORT_SCHEMA_VERSION,
            "models": sorted(registry),
            "valid_fixtures": manifest_fixtures,
            "invalid_fixtures": manifest_invalid,
        }
    )
    return files


def write_export(root: Path) -> list[Path]:
    target = root / EXPORT_DIRECTORY
    files = build_export()
    written: list[Path] = []
    for relative, content in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    expected = {target / relative for relative in files}
    for existing in target.rglob("*.json"):
        if existing not in expected:
            existing.unlink()
    return written


def drift(root: Path) -> list[str]:
    target = root / EXPORT_DIRECTORY
    files = build_export()
    problems = [
        f"missing or outdated: {relative}"
        for relative, content in files.items()
        if not (target / relative).is_file()
        or (target / relative).read_text(encoding="utf-8") != content
    ]
    if target.is_dir():
        known = set(files)
        problems.extend(
            f"unexpected: {path.relative_to(target).as_posix()}"
            for path in target.rglob("*.json")
            if path.relative_to(target).as_posix() not in known
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export studio.local contracts and fixtures")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        problems = drift(args.root)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    written = write_export(args.root)
    print(f"wrote {len(written)} files under {args.root / EXPORT_DIRECTORY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
