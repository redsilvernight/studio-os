from __future__ import annotations

from typing import Any

from pydantic import ValidationError


def validation_error(exc: ValidationError) -> dict[str, Any]:
    return {
        "error_code": "invalid_argument",
        "message": "invalid tool arguments",
        "fields": [
            {
                "field": ".".join(str(part) for part in error["loc"])[:100],
                "type": str(error["type"])[:80],
            }
            for error in exc.errors(include_input=False, include_context=False, include_url=False)[
                :3
            ]
        ],
    }
