"""Export the canonical OpenAPI document from the local backend.

Usage (from dashboard/):  npm run openapi:export
Requires the backend venv (../.venv) — falls back to the checked-in
openapi.json snapshot when the backend is not importable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
DASHBOARD = HERE.parent.parent
REPO = DASHBOARD.parent
OUT = DASHBOARD / "openapi.json"


def main() -> int:
    src = REPO / "services" / "api" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from studio_api.main import create_app
    except Exception as exc:  # noqa: BLE001 — documented fallback path
        print(f"backend not importable ({exc}); keeping checked-in snapshot.", file=sys.stderr)
        return 0
    doc = create_app().openapi()
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(doc.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
