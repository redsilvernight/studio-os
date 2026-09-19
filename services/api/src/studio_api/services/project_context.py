"""Bounded, deterministic project context for an agent's first call (DEC-0080).

A read-only *selection* over shared state the existing services already
expose — never a second source of truth. Every row is obtained through the
same service function the normal surfaces use (`projects`, `tasks`,
`decisions`, `library`, `claims`), so visibility, shadowing and scope rules
are those services' rules, not re-implemented here. No SQL of its own, no
write, no LLM, no embedding.

Relevance is only what Studi'OS can establish and explain:

* structural links — the requested task, decisions attached to it, claims on
  it or overlapping the given `files`, project-scope Library definitions;
* lexical overlap — exact token match between the objective and an item's
  title/body (stop words and short tokens dropped, no stemming).

Every returned item says which of the two selected it (`why`).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.library import LibraryKind, RuleContent, SkillContent

from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.task import TaskModel
from studio_api.services import claims as claims_service
from studio_api.services import decisions as decisions_service
from studio_api.services import library as library_service
from studio_api.services import projects as projects_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal

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

_TOKEN_RE = re.compile(r"[^\W_]+")
_STOPWORDS = frozenset(
    (
        # English
        "the and for with from that this into onto about over under than then "
        "when where what which while will would should could can may must not "
        "are was were been being has have had our your their its any all "
        "each other some such only also use using used new add fix "
        # French
        "les des une aux pour par sur dans avec sans sous entre vers chez "
        "que qui quoi dont est sont etre avoir fait faire mais donc car "
        "ces cet cette son ses leur leurs mon mes ton tes nos vos notre votre "
        "plus tout tous toute toutes aussi comme lors puis ainsi "
        "aux du de la le un en et ou ne pas"
    ).split()
)

Reason = Literal[
    "requested", "linked_to_task", "task_claim", "path_conflict", "project_scope", "lexical"
]


class Why(BaseModel):
    """Why an item was selected — the only two relations Studi'OS knows how to
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


class ContextLimits(BaseModel):
    limit: int
    max_chars: int
    chars_used: int
    item_text_cap: int
    library_scan_capped: bool = False


class PreparedContext(BaseModel):
    project: ProjectRef
    query_terms: list[str]
    task: TaskItem | None = None
    related_tasks: list[TaskItem] = []
    decisions: list[DecisionItem] = []
    rules: list[LibraryItem] = []
    skills: list[LibraryItem] = []
    active_work: ActiveWork = ActiveWork()
    returned: dict[str, int]
    additional_available: dict[str, int]
    omitted_for_budget: dict[str, int] = {}
    limits: ContextLimits


def _invalid(message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_400_BAD_REQUEST, detail={"error_code": "invalid_argument", "message": message}
    )


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, detail={"error_code": "not_found", "message": message}
    )


def tokens(text: str) -> list[str]:
    """Lowercased alphanumeric tokens in order of appearance (`_`, `.`, `-`
    and every other separator split)."""
    return _TOKEN_RE.findall(text.lower())


def query_terms(objective: str) -> list[str]:
    """Distinct objective terms in order of first appearance: at least
    `MIN_TERM_LENGTH` characters, not purely numeric, not a stop word,
    capped at `MAX_QUERY_TERMS`."""
    seen: dict[str, None] = {}
    for token in tokens(objective):
        if len(token) < MIN_TERM_LENGTH or token.isdigit() or token in _STOPWORDS:
            continue
        seen.setdefault(token, None)
        if len(seen) == MAX_QUERY_TERMS:
            break
    return list(seen)


def score(terms: list[str], title: str, body: str = "") -> tuple[int, list[str]]:
    """A term found in the title is worth 3, in the body 1 (never both).
    Returns `(score, matched terms in query order)`."""
    title_tokens = set(tokens(title))
    body_tokens = set(tokens(body))
    total = 0
    matched: list[str] = []
    for term in terms:
        if term in title_tokens:
            total += 3
            matched.append(term)
        elif term in body_tokens:
            total += 1
            matched.append(term)
    return total, matched


def _why(reason: Reason, matched: list[str]) -> Why:
    return Why(reason=reason, matched_terms=matched[:MAX_MATCHED_TERMS_SHOWN])


class _Budget:
    """Character budget over free-text fields (task/decision/rule/skill bodies,
    project description). Each text is first capped at `ITEM_TEXT_CAP`; when the
    remainder cannot hold it, it is cut to the remainder if that is at least
    `MIN_TEXT_CHARS`, otherwise the item is refused. Identifiers, titles and
    other fixed fields are bounded by the per-kind item cap instead."""

    def __init__(self, max_chars: int) -> None:
        self.remaining = max_chars
        self.used = 0

    def take(self, text: str, cap: int = ITEM_TEXT_CAP) -> tuple[str, bool] | None:
        capped = text[:cap]
        truncated = len(text) > cap
        if len(capped) > self.remaining:
            if self.remaining < MIN_TEXT_CHARS:
                return None
            capped = capped[: self.remaining]
            truncated = True
        self.remaining -= len(capped)
        self.used += len(capped)
        return capped, truncated


def _task_item(task: TaskModel, principal: Principal, why: Why, budget: _Budget) -> TaskItem | None:
    taken = budget.take(task.description or "")
    if taken is None:
        return None
    text, truncated = taken
    return TaskItem(
        id=task.id,
        readable_id=task.readable_id,
        title=task.title,
        status=task.status,
        description=text or None,
        truncated=truncated,
        claimed_by_machine_id=task.claimed_by_machine_id,
        claimed_by_self=task.claimed_by_machine_id == principal.machine.id,
        why=why,
    )


async def _select_tasks(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    terms: list[str],
    limit: int,
    budget: _Budget,
    omitted: dict[str, int],
) -> tuple[TaskItem | None, list[TaskItem], int]:
    requested: TaskItem | None = None
    if task_id is not None:
        task = await tasks_service.get_task(session, task_id)
        # Missing and foreign-project ids are one and the same answer: the
        # facade never reveals that a task exists in another project.
        if task is None or task.project_id != project_id:
            raise _not_found(f"task {task_id} not found in project {project_id}")
        requested = _task_item(task, principal, _why("requested", []), budget)
        if requested is None:
            omitted["task"] = 1

    active = await projects_service.get_active_tasks(session, project_id)
    candidates = [t for t in active if t.id != task_id]
    ranked: list[tuple[int, str, str, TaskModel, list[str]]] = []
    for candidate in candidates:
        value, matched = score(terms, candidate.title, candidate.description or "")
        if value > 0:
            ranked.append((value, candidate.title, str(candidate.id), candidate, matched))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))

    related: list[TaskItem] = []
    for _, _, _, candidate, matched in ranked:
        if len(related) == limit:
            break
        item = _task_item(candidate, principal, _why("lexical", matched), budget)
        if item is None:
            omitted["related_tasks"] = omitted.get("related_tasks", 0) + 1
            continue
        related.append(item)
    return requested, related, len(candidates)


async def _select_decisions(
    session: AsyncSession,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    terms: list[str],
    limit: int,
    budget: _Budget,
    omitted: dict[str, int],
) -> tuple[list[DecisionItem], int]:
    rows = [
        d
        for d in await decisions_service.list_decisions(session, project_id=project_id)
        if d.status != "superseded"
    ]
    ranked: list[tuple[int, int, int, float, str, DecisionModel, Why]] = []
    for row in rows:
        value, matched = score(terms, row.title, row.body)
        linked = task_id is not None and row.task_id == task_id
        if not linked and value == 0:
            continue
        why = _why("linked_to_task" if linked else "lexical", matched)
        ranked.append(
            (
                0 if linked else 1,
                -value,
                0 if row.status == "accepted" else 1,
                -row.created_at.timestamp(),
                row.readable_id,
                row,
                why,
            )
        )
    ranked.sort(key=lambda entry: entry[:5])

    picked: list[DecisionItem] = []
    for *_, row, why in ranked:
        if len(picked) == limit:
            break
        taken = budget.take(row.body)
        if taken is None:
            omitted["decisions"] = omitted.get("decisions", 0) + 1
            continue
        body, truncated = taken
        picked.append(
            DecisionItem(
                id=row.id,
                readable_id=row.readable_id,
                title=row.title,
                status=row.status,
                task_id=row.task_id,
                body=body,
                truncated=truncated,
                why=why,
            )
        )
    return picked, len(rows)


_SCOPE_RANK = {"project": 0, "user": 1, "studio": 2}


async def _select_library(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    kind: LibraryKind,
    terms: list[str],
    limit: int,
    budget: _Budget,
    omitted: dict[str, int],
) -> tuple[list[LibraryItem], int, bool]:
    """Effective definitions of one textual kind for this project.

    Candidate keys come from `library.list_resources` (already visibility
    filtered — another user's private rows never appear), then each key is
    resolved by `library.resolve_definition` (shadowing User > Project > Studio,
    project locks, unusable versions rejected). Deprecated definitions are not
    recommended as context and are left out of the counts."""
    keys: set[str] = set()
    capped = False
    for scope, scope_project in (("project", project_id), ("studio", None), ("user", None)):
        rows = await library_service.list_resources(
            session,
            principal,
            kind=kind.value,
            scope=scope,
            project_id=scope_project,
            limit=LIBRARY_SCAN_CAP,
        )
        capped = capped or len(rows) == LIBRARY_SCAN_CAP
        keys.update(r.stable_key for r in rows)

    ranked: list[tuple[int, int, str, LibraryItem]] = []
    total = 0
    for key in sorted(keys):
        try:
            resolved = await library_service.resolve_definition(
                session, principal, kind, key, project_id
            )
        except HTTPException:
            continue  # unusable or invisible: same silence as the normal surfaces
        if resolved.deprecated:
            continue
        version_row = await library_service.get_version(
            session, resolved.resource_id, resolved.version
        )
        if version_row is None:
            continue
        content_model = RuleContent if kind is LibraryKind.RULE else SkillContent
        try:
            text = content_model.model_validate(version_row.content).text
        except ValueError:
            continue
        total += 1
        value, matched = score(
            terms, f"{key} {version_row.title}", f"{version_row.description or ''} {text}"
        )
        scope_value = resolved.scope.value
        if value == 0 and scope_value != "project":
            continue
        reason: Reason = "lexical" if value > 0 else "project_scope"
        item = LibraryItem(
            kind=kind.value,  # type: ignore[arg-type]
            stable_key=key,
            title=version_row.title,
            scope=scope_value,
            version=resolved.version,
            version_origin=resolved.version_origin.value,
            text=text,
            why=_why(reason, matched),
        )
        ranked.append((-value, _SCOPE_RANK.get(scope_value, 9), key, item))
    ranked.sort(key=lambda entry: entry[:3])

    picked: list[LibraryItem] = []
    for *_, item in ranked:
        if len(picked) == limit:
            break
        taken = budget.take(item.text)
        if taken is None:
            name = f"{kind.value}s"
            omitted[name] = omitted.get(name, 0) + 1
            continue
        item.text, item.truncated = taken
        picked.append(item)
    return picked, total, capped


def _claim_item(claim: ResourceClaimModel, principal: Principal, why: Why) -> ClaimItem:
    return ClaimItem(
        id=claim.id,
        resource_path=claim.resource_path,
        resource_type=claim.resource_type,
        task_id=claim.task_id,
        claimed_by_machine_id=claim.claimed_by_machine_id,
        claimed_by_self=claim.claimed_by_machine_id == principal.machine.id,
        expires_at=claim.expires_at,
        why=why,
    )


async def _select_claims(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    files: list[str],
    limit: int,
) -> tuple[list[ClaimItem], int]:
    """Active (TTL-live) claims tied to the work at hand: those on the requested
    task, and — held by another machine — those overlapping `files` under the
    exact rule claims themselves use. Claims warn, they never block."""
    claims = await projects_service.get_active_claims(session, project_id)
    ranked: list[tuple[int, str, str, ResourceClaimModel, Why]] = []
    for claim in claims:
        is_other = claim.claimed_by_machine_id != principal.machine.id
        conflicts = is_other and any(
            claims_service.paths_conflict(claim.resource_path, claim.resource_type, path, "file")
            for path in files
        )
        if conflicts:
            ranked.append((0, claim.resource_path, str(claim.id), claim, _why("path_conflict", [])))
        elif task_id is not None and claim.task_id == task_id:
            ranked.append((1, claim.resource_path, str(claim.id), claim, _why("task_claim", [])))
    ranked.sort(key=lambda entry: entry[:3])
    picked = [_claim_item(claim, principal, why) for *_, claim, why in ranked[:limit]]
    return picked, len(claims)


def _clean_files(files: list[str] | None) -> list[str]:
    if files is None:
        return []
    if len(files) > MAX_FILES:
        raise _invalid(f"files accepts at most {MAX_FILES} paths")
    cleaned: list[str] = []
    for raw in files:
        path = raw.strip()
        if not path or len(path) > MAX_PATH_CHARS:
            raise _invalid(f"each file must be 1..{MAX_PATH_CHARS} characters")
        cleaned.append(path)
    return sorted(set(cleaned))


async def prepare_project_context(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    objective: str,
    task_id: uuid.UUID | None = None,
    files: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> PreparedContext:
    """Select the shared context relevant to `objective` on one project.

    Read-only and open to every authenticated role, exactly like the
    `get`/`list` surfaces it composes. Identical shared state and identical
    arguments always produce an identical result (no clock other than claim
    TTLs, no randomness)."""
    objective = objective.strip()
    if not objective or len(objective) > OBJECTIVE_MAX_CHARS:
        raise _invalid(f"objective must be 1..{OBJECTIVE_MAX_CHARS} characters")
    if not 1 <= limit <= MAX_LIMIT:
        raise _invalid(f"limit must be within 1..{MAX_LIMIT}")
    if not MIN_MAX_CHARS <= max_chars <= MAX_MAX_CHARS:
        raise _invalid(f"max_chars must be within {MIN_MAX_CHARS}..{MAX_MAX_CHARS}")
    paths = _clean_files(files)

    project = await projects_service.get_project(session, project_id)
    if project is None:
        raise _not_found(f"project {project_id} not found")

    terms = query_terms(objective)
    budget = _Budget(max_chars)
    omitted: dict[str, int] = {}

    # Cap (400) plus the smallest budget (1000) always leaves the requested
    # task at least MIN_TEXT_CHARS, so the anchor of the request is never refused.
    described = budget.take(project.description or "", PROJECT_DESCRIPTION_CAP)
    assert described is not None
    project_ref = ProjectRef(
        id=project.id,
        slug=project.slug,
        name=project.name,
        description=described[0] or None,
        truncated=described[1],
    )

    task, related, related_total = await _select_tasks(
        session, principal, project_id, task_id, terms, limit, budget, omitted
    )
    claims, claims_total = await _select_claims(
        session, principal, project_id, task_id, paths, limit
    )
    decisions, decisions_total = await _select_decisions(
        session, project_id, task_id, terms, limit, budget, omitted
    )
    rules, rules_total, rules_capped = await _select_library(
        session, principal, project_id, LibraryKind.RULE, terms, limit, budget, omitted
    )
    skills, skills_total, skills_capped = await _select_library(
        session, principal, project_id, LibraryKind.SKILL, terms, limit, budget, omitted
    )

    returned = {
        "task": 1 if task else 0,
        "related_tasks": len(related),
        "decisions": len(decisions),
        "rules": len(rules),
        "skills": len(skills),
        "claims": len(claims),
    }
    additional = {
        "related_tasks": related_total - len(related),
        "decisions": decisions_total - len(decisions),
        "rules": rules_total - len(rules),
        "skills": skills_total - len(skills),
        "claims": claims_total - len(claims),
    }
    return PreparedContext(
        project=project_ref,
        query_terms=terms,
        task=task,
        related_tasks=related,
        decisions=decisions,
        rules=rules,
        skills=skills,
        active_work=ActiveWork(claims=claims),
        returned=returned,
        additional_available=additional,
        omitted_for_budget=dict(sorted(omitted.items())),
        limits=ContextLimits(
            limit=limit,
            max_chars=max_chars,
            chars_used=budget.used,
            item_text_cap=ITEM_TEXT_CAP,
            library_scan_capped=rules_capped or skills_capped,
        ),
    )
