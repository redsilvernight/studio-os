"""Contrôle de code mort (PC5) : vulture pour Python, knip pour dashboard/ et desktop/.

Point d'entrée unique, en local comme en CI :

    uv run python -m scripts.deadcode_check            # tout
    uv run python -m scripts.deadcode_check --python   # vulture seul
    uv run python -m scripts.deadcode_check --js       # knip seul (dashboard: npm ci requis)

vulture lit `[tool.vulture]` du pyproject.toml de `--root` ; knip lit `knip.jsonc` de chaque
projet. Code de sortie non nul dès qu'un outil signale du code mort. Procédure :
docs/library/roadmap-pc/PC5-guard.md.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

KNIP = "knip@6.45.1"
JS_PROJECTS = ("dashboard", "desktop")
REPO = Path(__file__).resolve().parents[1]


def _run(label: str, cmd: list[str], cwd: Path) -> bool:
    start = time.monotonic()
    code = subprocess.run(cmd, cwd=cwd, check=False).returncode
    status = "ok" if code == 0 else f"KO (code {code})"
    print(f"[deadcode] {label} : {status} en {time.monotonic() - start:.1f} s", flush=True)
    return code == 0


def check_python(root: Path) -> bool:
    return _run("vulture", [sys.executable, "-m", "vulture"], root)


def check_js(root: Path) -> bool:
    npx = shutil.which("npx")
    if npx is None:
        print("[deadcode] npx introuvable : installer Node 22", file=sys.stderr)
        return False
    cmd = [npx, "--yes", KNIP, "--no-progress", "--reporter", "compact"]
    return all([_run(f"knip {name}", cmd, root / name) for name in JS_PROJECTS])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python", action="store_true", help="vulture seulement")
    parser.add_argument("--js", action="store_true", help="knip seulement")
    parser.add_argument("--root", type=Path, default=REPO, help="racine du dépôt à contrôler")
    args = parser.parse_args(argv)
    both = not (args.python or args.js)
    ok = True
    if both or args.python:
        ok = check_python(args.root) and ok
    if both or args.js:
        ok = check_js(args.root) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
