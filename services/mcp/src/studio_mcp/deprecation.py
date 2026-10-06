"""Deprecation of redundant MCP tools (DEC-0186).

A deprecated tool keeps its exact behaviour during the transition window; it is
only labelled, so a consumer reading `tools/list` or a response learns what to
call instead and when the tool goes away. Registration wraps the tool function
(`deprecated`) — the functions themselves, and the closures `ensure_tool_allowed`
names the tool from, are untouched.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

# First day the deprecated tools may be removed. Removal itself is a later,
# separate change (tests and consumers migrate first).
SUNSET = "2026-11-04"

# Deprecated tool -> the tool that replaces it.
REPLACED_BY: Mapping[str, str] = {
    "studio_start_session": "studio_start_work",
    "studio_end_session": "studio_handoff",
    "studio_claim_task": "studio_start_work",
    "studio_release_task": "studio_handoff",
    "studio_claim_resource": "studio_claim_resources",
}


def deprecation_notice(name: str) -> dict[str, str]:
    return {"replaced_by": REPLACED_BY[name], "sunset": SUNSET}


def deprecated_description(name: str, description: str) -> str:
    return (
        f"DEPRECATED, removal on or after {SUNSET}: use {REPLACED_BY[name]} instead. {description}"
    )


def deprecated(
    name: str, fn: Callable[..., Awaitable[dict[str, Any]]]
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Wrap a tool function so every successful answer carries a `deprecation`
    object (`replaced_by`, `sunset`). Errors are returned untouched."""
    notice = deprecation_notice(name)

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = await fn(*args, **kwargs)
        if isinstance(result, dict) and "error_code" not in result:
            return {**result, "deprecation": notice}
        return result

    return wrapper
