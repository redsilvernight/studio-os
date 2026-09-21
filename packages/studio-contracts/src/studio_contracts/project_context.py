"""Canonical wire shape of `studio_prepare_context` (P2 context contract).

Single source of truth for the bounded context payload shared by the MCP
facade and Bloc B: every model below was previously defined in
`studio_api.services.project_context` / `project_context_roadmap` /
`context_why` and is re-exported there unchanged, so the existing MCP
payload is byte-compatible (plus the additive `ai_work` section, P2.3).

Compatibility rules (TECH/07, DEC-0048/DEC-0088):

* additive-only — new optional sections default to empty/absent, never `null`
  without object;
* no per-payload version: readers must ignore what they do not know (plain
  `BaseModel`, deliberately not `extra="forbid"` — a section such as
  `roadmap` is a super-set of its base contract and must never be validated
  against it);
* the Roadmap models extend `studio_contracts.roadmaps` (`ContextStep`,
  `RoadmapContext`) without altering them.

Budget semantics (P2.2) — the single canonical rule, tokenizer-independent:

* the server budget counts **characters** (`len()`, i.e. Unicode scalar
  values) of free-text fields only; identifiers, titles, ids and other fixed
  fields are bounded by per-kind caps instead;
* selection is deterministic (structural links, then exact-token overlap —
  no clock other than claim TTLs, no randomness, no LLM, no embedding);
* Bloc B's byte budget (`ContextPackageComposer`, UTF-8 octets) is a
  transport-local concern for the locally composed package, not part of this
  contract: bytes on the wire, characters in the selection.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer

from studio_contracts.roadmaps import (
    ContextStep,
    Progress,
    RoadmapContext,
    RoadmapStatus,
)

DEFAULT_LIMIT = 5
MAX_LIMIT = 20
DEFAULT_MAX_CHARS = 12_000
MIN_MAX_CHARS = 1_000
MAX_MAX_CHARS = 50_000
ITEM_TEXT_CAP = 1_500
PROJECT_DESCRIPTION_CAP = 400
MIN_TEXT_CHARS = 200
OBJECTIVE_MAX_CHARS = 1_000
MAX_QUERY_TERMS = 24
MAX_FILES = 20
MAX_PATH_CHARS = 500
LIBRARY_SCAN_CAP = 200
MIN_TERM_LENGTH = 3
MAX_MATCHED_TERMS_SHOWN = 5
ROADMAP_BUDGET_SHARE = 0.25
AIWORK_BUDGET_SHARE = 0.15
AIWORK_LIST_CAP = 10

Reason = Literal[
    "requested",
    "linked_to_task",
    "task_claim",
    "path_conflict",
    "project_scope",
    "lexical",
    "active_roadmap",
]

TaskLocation = Literal["task", "related_tasks"]


class Why(BaseModel):
    """Why an item was selected — the only relations Studi'OS knows how to
    establish: a structural link, or an exact-token overlap with the objective."""

    reason: Reason
    matched_terms: list[str] = []


class ProjectRef(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None = None
    truncated: bool = False


class TaskItem(BaseModel):
    id: uuid.UUID
    readable_id: str | None = None
    title: str
    status: str
    description: str | None = None
    truncated: bool = False
    claimed_by_machine_id: uuid.UUID | None = None
    claimed_by_self: bool = False
    why: Why


class DecisionItem(BaseModel):
    id: uuid.UUID
    readable_id: str
    title: str
    status: str
    task_id: uuid.UUID | None = None
    body: str
    truncated: bool = False
    why: Why


class LibraryItem(BaseModel):
    kind: Literal["rule", "skill"]
    stable_key: str
    title: str
    scope: str
    version: int
    version_origin: str
    text: str
    truncated: bool = False
    why: Why


class ClaimItem(BaseModel):
    id: uuid.UUID
    resource_path: str
    resource_type: str
    task_id: uuid.UUID | None = None
    claimed_by_machine_id: uuid.UUID
    claimed_by_self: bool
    expires_at: datetime
    why: Why


class ActiveWork(BaseModel):
    claims: list[ClaimItem] = []


class AIWorkItem(BaseModel):
    """One AI work entry relevant to the objective (P2.3): the handoff resume
    packet. `truncated` covers the summary as well as the capped file/test
    lists — anything cut is counted, never silently dropped, via
    `additional_available` / `omitted_for_budget`."""

    id: uuid.UUID
    status: str
    summary: str
    truncated: bool = False
    changed_files: list[str] = []
    tests_run: list[str] = []
    started_at: datetime
    ended_at: datetime | None = None
    why: Why


class ContextLimits(BaseModel):
    limit: int
    max_chars: int
    chars_used: int
    item_text_cap: int
    library_scan_capped: bool = False
    roadmap_scan_capped: bool = False

    @model_serializer(mode="wrap")
    def _drop_unset_roadmap_cap(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Absent, not `false`, until the Roadmap scan actually hit its ceiling."""
        data: dict[str, Any] = handler(self)
        if not data.get("roadmap_scan_capped"):
            data.pop("roadmap_scan_capped", None)
        return data


class RoadmapTaskRef(BaseModel):
    """A Task linked to a step: a bare reference when the package already
    carries it (`in_context`), a title and status otherwise."""

    id: uuid.UUID
    title: str | None = None
    status: str | None = None
    in_context: TaskLocation | None = None


class RoadmapStepItem(ContextStep):
    """A step the agent may work on now: the shared `ContextStep` plus its
    objective and the Tasks tied to it. `acceptance_criteria` lists the criteria
    still to satisfy (already checked ones are only counted)."""

    objective: str | None = None
    truncated: bool = False
    criteria_total: int = 0
    criteria_checked: int = 0
    linked_tasks: list[RoadmapTaskRef] = []


class RoadmapItem(RoadmapContext):
    """`RoadmapContext` (TECH/07) extended with the fields a consumer needs to
    trust it: status, provenance, truncation and the step of the requested Task."""

    status: RoadmapStatus
    objective: str | None = None
    truncated: bool = False
    current_step: RoadmapStepItem | None = None
    task_step: RoadmapStepItem | None = None
    why: Why


class RoadmapRef(BaseModel):
    id: uuid.UUID
    title: str
    status: RoadmapStatus
    progress: Progress
    truncated: bool = False


class RoadmapOverview(BaseModel):
    """Roadmaps other than the active one, by reference: what is waiting for a
    human decision (`draft_pending`) or finished."""

    counts: dict[str, int]
    draft_pending: int
    others: list[RoadmapRef] = []


class PreparedContext(BaseModel):
    project: ProjectRef
    query_terms: list[str]
    task: TaskItem | None = None
    related_tasks: list[TaskItem] = []
    decisions: list[DecisionItem] = []
    rules: list[LibraryItem] = []
    skills: list[LibraryItem] = []
    ai_work: list[AIWorkItem] = []
    active_work: ActiveWork = ActiveWork()
    roadmap: RoadmapItem | None = None
    roadmap_overview: RoadmapOverview | None = None
    unavailable: list[str] = []
    returned: dict[str, int]
    additional_available: dict[str, int]
    omitted_for_budget: dict[str, int] = {}
    limits: ContextLimits

    @model_serializer(mode="wrap")
    def _drop_absent_roadmap(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """A project without an `active` roadmap serialises exactly as before
        the Roadmap section existed: the additive fields are absent, not null."""
        data: dict[str, Any] = handler(self)
        for name in ("roadmap", "roadmap_overview"):
            if data.get(name) is None:
                data.pop(name, None)
        if not data.get("unavailable"):
            data.pop("unavailable", None)
        return data
