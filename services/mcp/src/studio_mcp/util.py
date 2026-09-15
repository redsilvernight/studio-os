from __future__ import annotations

from typing import Any
from uuid import UUID


def parse_uuid(raw: str, field: str) -> UUID | dict[str, Any]:
    """Returns the parsed UUID, or a machine-readable error dict a tool can
    return directly on a bad id."""
    try:
        return UUID(raw)
    except ValueError:
        return {"error_code": "invalid_argument", "message": f"{field} is not a UUID: {raw!r}"}
