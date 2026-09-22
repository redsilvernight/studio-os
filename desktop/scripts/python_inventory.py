import json
import re
import sys
from importlib.metadata import distributions
from pathlib import Path

ARCHIVED_MODULE = re.compile(r"\('([\w.]+)',\s*(?:'([^']+)'|\"([^\"]+)\"),\s*'PYMODULE'\)")


def frozen_names(internal: Path, archive_toc: Path) -> set[str]:
    names = {
        entry.name.split(".")[0]
        for entry in internal.iterdir()
        if not entry.name.endswith(".dist-info")
    }
    for module, single, double in ARCHIVED_MODULE.findall(archive_toc.read_text(encoding="utf-8")):
        if "site-packages" in (single or double):
            names.add(module.split(".")[0])
    return names


def declared_license(text: str) -> str:
    head = text.split("\n\n", 1)[0]
    fields: dict[str, list[str]] = {}
    for line in head.splitlines():
        key, _, value = line.partition(": ")
        fields.setdefault(key.lower(), []).append(value.strip())
    expression = (fields.get("license-expression") or [""])[0]
    if expression:
        return expression
    plain = (fields.get("license") or [""])[0]
    if plain and len(plain) < 80:
        return plain
    classifiers = [
        value.split("License :: ", 1)[1].replace("OSI Approved :: ", "")
        for value in fields.get("classifier", [])
        if "License ::" in value
    ]
    return " / ".join(classifiers)


def main() -> None:
    present = frozen_names(Path(sys.argv[1]), Path(sys.argv[2]))
    packages: dict[str, dict[str, str]] = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        tops = {
            (f.parts[0]).split(".")[0]
            for f in (dist.files or [])
            if f.parts and not f.parts[0].endswith(".dist-info")
        }
        if not name or not (tops & present):
            continue
        packages[name.lower()] = {
            "name": name,
            "version": dist.version,
            "license": declared_license(dist.read_text("METADATA") or "") or "UNDECLARED",
            "ecosystem": "python",
        }
    json.dump(sorted(packages.values(), key=lambda p: p["name"].lower()), sys.stdout)


main()
