from __future__ import annotations

import json
from pathlib import Path
from typing import cast

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "contracts" / "fixtures"


def load_fixture(name: str) -> list[dict[str, object]]:
    raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return cast(list[dict[str, object]], raw)
