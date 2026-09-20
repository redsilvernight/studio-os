"""Selection provenance shared by every `studio_prepare_context` section (DEC-0080).

Kept apart from `project_context` so the Roadmap section (DEC-0088) can carry
the same `why` without a circular import.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Reason = Literal[
    "requested",
    "linked_to_task",
    "task_claim",
    "path_conflict",
    "project_scope",
    "lexical",
    "active_roadmap",
]


class Why(BaseModel):
    """Why an item was selected — the only relations Studi'OS knows how to
    establish: a structural link, or an exact-token overlap with the objective."""

    reason: Reason
    matched_terms: list[str] = []
