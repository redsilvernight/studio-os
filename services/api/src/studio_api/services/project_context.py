"""Bounded, deterministic project context for an agent's first call (DEC-0080).

A read-only *selection* over shared state the existing services already
expose — never a second source of truth. Every row is obtained through the
same service function the normal surfaces use (`projects`, `tasks`,
`decisions`, `library`, `ai_work`, `claims`, `vault`), so visibility,
shadowing and scope rules are those services' rules, not re-implemented
here. No SQL of its own, no write, no LLM, no embedding.

Wire models and budget constants live in `studio_contracts.project_context`
(P2 canonical contract) and are re-exported here unchanged, so the MCP
payload stays compatible.

Relevance is only what Studi'OS can establish and explain:

* structural links — the requested task, decisions and recent AI work
  attached to it, claims on it or overlapping the given `files`,
  project-scope Library definitions, vault notes anchored to the task or to
  a declared path and the notes one link away from them;
* lexical overlap — exact token match between the objective and an item's
  title/body (stop words and short tokens dropped, no stemming).

Every returned item says which of the two selected it (`why`).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.library import LibraryKind, RuleContent, SkillContent
from studio_contracts.project_context import (
    AIWORK_BUDGET_SHARE,
    AIWORK_LIST_CAP,
    DEFAULT_LIMIT,
    DEFAULT_MAX_CHARS,
    ITEM_TEXT_CAP,
    LIBRARY_SCAN_CAP,
    MAX_FILES,
    MAX_KNOWN_IDS,
    MAX_LIMIT,
    MAX_MATCHED_TERMS_SHOWN,
    MAX_MAX_CHARS,
    MAX_PATH_CHARS,
    MAX_QUERY_TERMS,
    MAX_SOURCE_REFERENCES,
    MIN_MAX_CHARS,
    MIN_TERM_LENGTH,
    MIN_TEXT_CHARS,
    NOTE_SUMMARY_CAP,
    NOTES_BUDGET_SHARE,
    OBJECTIVE_MAX_CHARS,
    PROJECT_DESCRIPTION_CAP,
    ROADMAP_BUDGET_SHARE,
    ActiveWork,
    AIWorkItem,
    ClaimItem,
    ContextLimits,
    DecisionItem,
    LibraryItem,
    NoteItem,
    PreparedContext,
    ProjectRef,
    TaskItem,
)
from studio_contracts.vault import (
    VAULT_SEARCH_SNIPPET_MAX,
    VaultNoteStatus,
    VaultSearchHit,
    VaultSearchReason,
)

from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.task import TaskModel
from studio_api.services import ai_work as ai_work_service
from studio_api.services import claims as claims_service
from studio_api.services import decisions as decisions_service
from studio_api.services import library as library_service
from studio_api.services import projects as projects_service
from studio_api.services import tasks as tasks_service
from studio_api.services import vault as vault_service
from studio_api.services.authz import Principal
from studio_api.services.context_why import Reason, Why
from studio_api.services.project_context_roadmap import (
    RoadmapItem,
    RoadmapOverview,
    TaskLocation,
    select_roadmap,
)

__all__ = [
    # Canonical contract re-exports (live in studio_contracts.project_context).
    "AIWORK_BUDGET_SHARE",
    "AIWORK_LIST_CAP",
    "DEFAULT_LIMIT",
    "DEFAULT_MAX_CHARS",
    "ITEM_TEXT_CAP",
    "LIBRARY_SCAN_CAP",
    "MAX_FILES",
    "MAX_KNOWN_IDS",
    "MAX_LIMIT",
    "MAX_MATCHED_TERMS_SHOWN",
    "MAX_MAX_CHARS",
    "MAX_PATH_CHARS",
    "MAX_QUERY_TERMS",
    "MAX_SOURCE_REFERENCES",
    "MIN_MAX_CHARS",
    "MIN_TERM_LENGTH",
    "MIN_TEXT_CHARS",
    "NOTES_BUDGET_SHARE",
    "NOTE_SUMMARY_CAP",
    "OBJECTIVE_MAX_CHARS",
    "PROJECT_DESCRIPTION_CAP",
    "ROADMAP_BUDGET_SHARE",
    "ActiveWork",
    "AIWorkItem",
    "ClaimItem",
    "ContextLimits",
    "DecisionItem",
    "LibraryItem",
    "NoteItem",
    "PreparedContext",
    "ProjectRef",
    "RoadmapItem",
    "RoadmapOverview",
    "TaskItem",
    "TaskLocation",
    # Selection entry points.
    "prepare_project_context",
    "query_terms",
    "score",
    "source_references",
    "tokens",
]

_TOKEN_RE = re.compile(r"[^\W_]+")
_SOURCE_RE = re.compile(r"^\s*(?:[-*]\s*)?sources?\s*:\s*(.+?)\s*$", re.IGNORECASE)
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


def source_references(description: str | None) -> list[str]:
    if not description:
        return []
    references: list[str] = []
    for line in description.splitlines():
        match = _SOURCE_RE.match(line)
        if match is None:
            continue
        for part in re.split(r"[;,]", match.group(1)):
            value = part.strip().strip("\"'").strip()
            if value and len(value) <= MAX_PATH_CHARS and value not in references:
                references.append(value)
            if len(references) == MAX_SOURCE_REFERENCES:
                break
        if len(references) == MAX_SOURCE_REFERENCES:
            break
    return references


def _content_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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

    def take_whole(self, text: str) -> bool:
        """Spend `len(text)` only if all of it fits — for identifiers, which are
        never cut."""
        if len(text) > self.remaining:
            return False
        self.remaining -= len(text)
        self.used += len(text)
        return True

    def mark(self) -> int:
        return self.used

    def rollback(self, mark: int) -> None:
        """Refund everything spent since `mark` (a section that failed)."""
        self.remaining += self.used - mark
        self.used = mark

    def slice(self, ceiling: int) -> _BudgetSlice:
        return _BudgetSlice(self, ceiling)


class _BudgetSlice(_Budget):
    """A ceiling over the shared budget: every character spent is charged to
    both, so `chars_used` stays the true total while one section cannot take
    more than its share of what is left."""

    def __init__(self, parent: _Budget, ceiling: int) -> None:
        super().__init__(min(ceiling, parent.remaining))
        self._parent = parent

    def take(self, text: str, cap: int = ITEM_TEXT_CAP) -> tuple[str, bool] | None:
        taken = super().take(text, cap)
        if taken is not None:
            self._parent.remaining -= len(taken[0])
            self._parent.used += len(taken[0])
        return taken

    def take_whole(self, text: str) -> bool:
        if not super().take_whole(text):
            return False
        self._parent.remaining -= len(text)
        self._parent.used += len(text)
        return True

    def rollback(self, mark: int) -> None:
        refund = self.used - mark
        super().rollback(mark)
        self._parent.remaining += refund
        self._parent.used -= refund


def _task_item(
    task: TaskModel,
    principal: Principal,
    why: Why,
    budget: _Budget,
    known_ids: Mapping[uuid.UUID, str],
) -> TaskItem | None:
    content_hash = _content_hash(task.description or "")
    if known_ids.get(task.id) == content_hash:
        return TaskItem(
            id=task.id,
            readable_id=task.readable_id,
            title=task.title,
            status=task.status,
            claimed_by_machine_id=task.claimed_by_machine_id,
            claimed_by_self=task.claimed_by_machine_id == principal.machine.id,
            content_hash=content_hash,
            unchanged=True,
            why=why,
        )
    taken = budget.take(task.description or "")
    if taken is None:
        return None
    text, truncated = taken
    references: list[str] = []
    all_references = source_references(task.description)
    for reference in all_references:
        if not budget.take_whole(reference):
            truncated = True
            break
        references.append(reference)
    return TaskItem(
        id=task.id,
        readable_id=task.readable_id,
        title=task.title,
        status=task.status,
        description=text or None,
        source_references=references,
        truncated=truncated,
        claimed_by_machine_id=task.claimed_by_machine_id,
        claimed_by_self=task.claimed_by_machine_id == principal.machine.id,
        content_hash=content_hash,
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
    known_ids: Mapping[uuid.UUID, str],
) -> tuple[TaskItem | None, list[TaskItem], int]:
    requested: TaskItem | None = None
    if task_id is not None:
        task = await tasks_service.get_task(session, task_id)
        # Missing and foreign-project ids are one and the same answer: the
        # facade never reveals that a task exists in another project.
        if task is None or task.project_id != project_id:
            raise _not_found(f"task {task_id} not found in project {project_id}")
        requested = _task_item(task, principal, _why("requested", []), budget, known_ids)
        if requested is None:
            omitted["task"] = 1

    active = await projects_service.get_active_tasks(session, principal, project_id)
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
        item = _task_item(candidate, principal, _why("lexical", matched), budget, known_ids)
        if item is None:
            omitted["related_tasks"] = omitted.get("related_tasks", 0) + 1
            continue
        related.append(item)
    return requested, related, len(candidates)


async def _select_decisions(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    terms: list[str],
    limit: int,
    budget: _Budget,
    omitted: dict[str, int],
    known_ids: Mapping[uuid.UUID, str],
) -> tuple[list[DecisionItem], int]:
    rows = [
        d
        for d in await decisions_service.list_decisions(session, principal, project_id=project_id)
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
        content_hash = _content_hash(row.body)
        if known_ids.get(row.id) == content_hash:
            picked.append(
                DecisionItem(
                    id=row.id,
                    readable_id=row.readable_id,
                    title=row.title,
                    status=row.status,
                    task_id=row.task_id,
                    body="",
                    content_hash=content_hash,
                    unchanged=True,
                    why=why,
                )
            )
            continue
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
                content_hash=content_hash,
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
    applicable: frozenset[tuple[str, int]] = frozenset(),
) -> tuple[list[LibraryItem], int, bool]:
    """Effective definitions of one textual kind for this project.

    Candidate keys come from `library.list_resources` (already visibility
    filtered — another user's private rows never appear), then each key is
    resolved by `library.resolve_definition` (shadowing User > Project > Studio,
    project locks, unusable versions rejected). Deprecated definitions are not
    recommended as context and are left out of the counts.

    `applicable` holds `(stable_key, version)` pairs from a resolved agent
    definition (P3.3): they are kept even without lexical overlap and sort
    first, flagged `agent_applies` — but they still compete for `limit` and
    budget. Resolution says what applies; disclosure decides what ships."""
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

    ranked: list[tuple[int, int, int, str, LibraryItem]] = []
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
        applies = (key, resolved.version) in applicable
        if value == 0 and scope_value != "project" and not applies:
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
            agent_applies=applies,
        )
        ranked.append((0 if applies else 1, -value, _SCOPE_RANK.get(scope_value, 9), key, item))
    ranked.sort(key=lambda entry: entry[:4])

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
    claims = await projects_service.get_active_claims(session, principal, project_id)
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


def _cap_str_list(values: list[str], cap: int = AIWORK_LIST_CAP) -> tuple[list[str], bool]:
    """Bound a string list for the wire: first `cap` entries plus whether the
    rest was cut. Pure and deterministic — unit-tested without a database."""
    if len(values) > cap:
        return values[:cap], True
    return list(values), False


def _ai_work_item(
    work: AIWorkLogModel,
    why: Why,
    budget: _Budget,
    known_ids: Mapping[uuid.UUID, str],
) -> AIWorkItem | None:
    """One work entry as context: the summary spends free-text budget, the
    file/test lists are count-bounded instead. `None` means the section ran
    out of budget and the entry is counted, not silently dropped."""
    content_hash = _content_hash(
        {
            "summary": work.summary or "",
            "changed_files": list(work.changed_files or []),
            "tests_run": list(work.tests_run or []),
        }
    )
    if known_ids.get(work.id) == content_hash:
        return AIWorkItem(
            id=work.id,
            status=work.status,
            summary="",
            started_at=work.started_at,
            ended_at=work.ended_at,
            content_hash=content_hash,
            unchanged=True,
            why=why,
        )
    taken = budget.take(work.summary or "")
    if taken is None:
        return None
    summary, summary_cut = taken
    changed_files, files_cut = _cap_str_list(list(work.changed_files or []))
    tests_run, tests_cut = _cap_str_list(list(work.tests_run or []))
    return AIWorkItem(
        id=work.id,
        status=work.status,
        summary=summary,
        truncated=summary_cut or files_cut or tests_cut,
        changed_files=changed_files,
        tests_run=tests_run,
        started_at=work.started_at,
        ended_at=work.ended_at,
        content_hash=content_hash,
        why=why,
    )


async def _select_ai_work(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    terms: list[str],
    limit: int,
    budget: _Budget,
    omitted: dict[str, int],
    known_ids: Mapping[uuid.UUID, str],
) -> tuple[list[AIWorkItem], int]:
    """Recent work relevant to the resume: entries on the requested task first
    (newest first — the handoff packet lives here), then entries whose summary
    lexically overlaps the objective. Bounded by `limit` and its own budget
    slice, so the section can neither starve nor swamp the rest."""
    rows = await ai_work_service.list_ai_work(session, principal, project_id=project_id)
    linked: list[tuple[float, str, AIWorkLogModel]] = []
    lexical: list[tuple[int, float, str, AIWorkLogModel, list[str]]] = []
    for row in rows:
        if task_id is not None and row.task_id == task_id:
            linked.append((-row.started_at.timestamp(), str(row.id), row))
        else:
            value, matched = score(terms, "", row.summary or "")
            if value > 0:
                lexical.append((-value, -row.started_at.timestamp(), str(row.id), row, matched))
    linked.sort(key=lambda entry: entry[:2])
    lexical.sort(key=lambda entry: entry[:3])

    picked: list[AIWorkItem] = []
    for _, _, row in linked:
        if len(picked) == limit:
            break
        item = _ai_work_item(row, _why("linked_to_task", []), budget, known_ids)
        if item is None:
            omitted["ai_work"] = omitted.get("ai_work", 0) + 1
            continue
        picked.append(item)
    for _, _, _, row, matched in lexical:
        if len(picked) == limit:
            break
        item = _ai_work_item(row, _why("lexical", matched), budget, known_ids)
        if item is None:
            omitted["ai_work"] = omitted.get("ai_work", 0) + 1
            continue
        picked.append(item)
    return picked, len(rows)


_VAULT_REASONS: dict[VaultSearchReason, Reason] = {
    VaultSearchReason.ANCHOR: "vault_anchor",
    VaultSearchReason.LINKED: "vault_link",
    VaultSearchReason.LEXICAL: "lexical",
}
_VAULT_STATUSES = [VaultNoteStatus.VALIDATED, VaultNoteStatus.PROPOSED]
# The read is bounded by `limit` hits and by these caps; the budget slice then
# decides what ships and what is counted as cut.
_VAULT_ITEM_MAX_CHARS = NOTE_SUMMARY_CAP + VAULT_SEARCH_SNIPPET_MAX


def _note_item(
    hit: VaultSearchHit,
    terms: list[str],
    budget: _Budget,
    known_ids: Mapping[uuid.UUID, str],
) -> NoteItem | None:
    """One vault hit as context: the summary and the search snippet spend free
    text budget, the body never ships — the full note is one
    `GET /vault/notes/{id}` away. `None` means the section ran out of budget and
    the note is counted, not silently dropped."""
    note = hit.note
    content_hash = note.content_hash
    why = _why(_VAULT_REASONS[hit.reason], score(terms, note.title, note.summary)[1])
    if known_ids.get(note.id) == content_hash:
        return NoteItem(
            id=note.id,
            scope=note.scope.value,
            readable_id=note.readable_id,
            slug=note.slug,
            note_type=note.note_type.value,
            title=note.title,
            status=note.status.value,
            summary="",
            snippet="",
            content_hash=content_hash,
            unchanged=True,
            why=why,
        )
    mark = budget.mark()
    summary = budget.take(note.summary, NOTE_SUMMARY_CAP)
    if summary is None:
        return None
    snippet = budget.take(hit.snippet)
    if snippet is None:
        budget.rollback(mark)
        return None
    return NoteItem(
        id=note.id,
        scope=note.scope.value,
        readable_id=note.readable_id,
        slug=note.slug,
        note_type=note.note_type.value,
        title=note.title,
        status=note.status.value,
        summary=summary[0],
        snippet=snippet[0],
        content_hash=content_hash,
        truncated=summary[1] or snippet[1],
        why=why,
    )


async def _select_notes(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    paths: list[str],
    terms: list[str],
    limit: int,
    budget: _Budget,
    omitted: dict[str, int],
    known_ids: Mapping[uuid.UUID, str],
) -> tuple[list[NoteItem], int, bool]:
    """Vault notes readable from this project (P07, DEC-0187 D6): its own notes
    plus the studio ones, `validated` and `proposed` only — never a draft, a
    superseded or an archived note. Anchors, then one link away, then full text,
    in the ranking `vault.search_notes` already applies to `GET /vault/search`.

    The read runs in a savepoint and never fails the context: an unreadable
    vault leaves the rest of the answer intact and is flagged `unavailable`."""
    if not terms and not paths and task_id is None:
        return [], 0, False
    mark = budget.mark()
    picked: list[NoteItem] = []
    refused = 0
    try:
        async with session.begin_nested():
            found = await vault_service.search_notes(
                session,
                principal,
                q=" ".join(terms) or None,
                scope=None,
                project_id=project_id,
                note_types=[],
                statuses=_VAULT_STATUSES,
                include_superseded=False,
                paths=paths,
                task_id=task_id,
                limit=limit,
                max_chars=limit * _VAULT_ITEM_MAX_CHARS,
            )
            for hit in found.items:
                if len(picked) == limit:
                    break
                item = _note_item(hit, terms, budget, known_ids)
                if item is None:
                    refused += 1
                    continue
                picked.append(item)
    except Exception:  # noqa: BLE001 - the vault is optional: whatever fails, the rest answers
        budget.rollback(mark)
        return [], 0, True

    if refused:
        omitted["notes"] = omitted.get("notes", 0) + refused
    return picked, found.total, False


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


async def _applicable_library(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    agent_stable_key: str,
) -> frozenset[tuple[str, int]]:
    """`(stable_key, version)` pairs the resolved agent definition applies
    (P3.3). Resolution failures propagate — an unknown agent is a 404, never
    a silent fallback to lexical-only selection (fail-closed)."""
    from studio_api.services import resolution as resolution_service

    resolved = await resolution_service.resolve_full(
        session, principal, LibraryKind.AGENT_DEFINITION, agent_stable_key, project_id
    )
    return frozenset(
        [(r.stable_key, r.version) for r in resolved.rules]
        + [(s.stable_key, s.version) for s in resolved.skills]
    )


async def prepare_project_context(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    objective: str | None,
    task_id: uuid.UUID | None = None,
    files: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    max_chars: int = DEFAULT_MAX_CHARS,
    agent_stable_key: str | None = None,
    known_ids: Mapping[uuid.UUID, str] | None = None,
) -> PreparedContext:
    """Select the shared context relevant to `objective` on one project.

    Read-only and open to every authenticated role, exactly like the
    `get`/`list` surfaces it composes. Identical shared state and identical
    arguments always produce an identical result (no clock other than claim
    TTLs, no randomness).

    `agent_stable_key` names the agent working (P3.3): its resolved
    rules/skills sort first and are flagged `agent_applies`, still bounded
    by `limit` and budget — resolution says what applies, disclosure
    decides what ships."""
    known_ids = known_ids or {}
    if not 1 <= limit <= MAX_LIMIT:
        raise _invalid(f"limit must be within 1..{MAX_LIMIT}")
    if not MIN_MAX_CHARS <= max_chars <= MAX_MAX_CHARS:
        raise _invalid(f"max_chars must be within {MIN_MAX_CHARS}..{MAX_MAX_CHARS}")
    if len(known_ids) > MAX_KNOWN_IDS:
        raise _invalid(f"known_ids accepts at most {MAX_KNOWN_IDS} ids")
    paths = _clean_files(files)

    project = await projects_service.get_project(session, principal, project_id)

    if objective is None or (task_id is not None and not objective.strip()):
        if task_id is None:
            raise _invalid("objective is required when task_id is omitted")
        objective_task = await tasks_service.get_task(session, task_id)
        if objective_task is None or objective_task.project_id != project_id:
            raise _not_found(f"task {task_id} not found in project {project_id}")
        objective = f"{objective_task.title}\n{objective_task.description or ''}"[
            :OBJECTIVE_MAX_CHARS
        ].strip()
    else:
        objective = objective.strip()
    if not objective or len(objective) > OBJECTIVE_MAX_CHARS:
        raise _invalid(f"objective must be 1..{OBJECTIVE_MAX_CHARS} characters")

    terms = query_terms(objective)
    budget = _Budget(max_chars)
    omitted: dict[str, int] = {}
    applicable: frozenset[tuple[str, int]] = frozenset()
    if agent_stable_key is not None:
        applicable = await _applicable_library(session, principal, project_id, agent_stable_key)

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
        session, principal, project_id, task_id, terms, limit, budget, omitted, known_ids
    )
    claims, claims_total = await _select_claims(
        session, principal, project_id, task_id, paths, limit
    )
    # Before decisions/rules/skills — which would otherwise drain the budget —
    # but under its own ceiling, so the Roadmap can neither starve nor swamp them.
    known_tasks: dict[uuid.UUID, TaskLocation] = {t.id: "related_tasks" for t in related}
    if task is not None:
        known_tasks[task.id] = "task"
    roadmap = await select_roadmap(
        session,
        principal,
        project_id,
        task_id,
        known_tasks,
        limit,
        budget.slice(int(max_chars * ROADMAP_BUDGET_SHARE)),
    )
    for name, count in roadmap.omitted.items():
        omitted[name] = omitted.get(name, 0) + count
    ai_work, ai_work_total = await _select_ai_work(
        session,
        principal,
        project_id,
        task_id,
        terms,
        limit,
        budget.slice(int(max_chars * AIWORK_BUDGET_SHARE)),
        omitted,
        known_ids,
    )
    decisions, decisions_total = await _select_decisions(
        session, principal, project_id, task_id, terms, limit, budget, omitted, known_ids
    )
    notes, notes_total, notes_unavailable = await _select_notes(
        session,
        principal,
        project_id,
        task_id,
        paths,
        terms,
        limit,
        budget.slice(int(max_chars * NOTES_BUDGET_SHARE)),
        omitted,
        known_ids,
    )
    rules, rules_total, rules_capped = await _select_library(
        session,
        principal,
        project_id,
        LibraryKind.RULE,
        terms,
        limit,
        budget,
        omitted,
        applicable,
    )
    skills, skills_total, skills_capped = await _select_library(
        session,
        principal,
        project_id,
        LibraryKind.SKILL,
        terms,
        limit,
        budget,
        omitted,
        applicable,
    )

    returned = {
        "task": 1 if task else 0,
        "related_tasks": len(related),
        "decisions": len(decisions),
        "rules": len(rules),
        "skills": len(skills),
        "ai_work": len(ai_work),
        "claims": len(claims),
    }
    additional = {
        "related_tasks": related_total - len(related),
        "decisions": decisions_total - len(decisions),
        "rules": rules_total - len(rules),
        "skills": skills_total - len(skills),
        "ai_work": ai_work_total - len(ai_work),
        "claims": claims_total - len(claims),
    }
    if roadmap.item is not None:
        returned["roadmap"] = 1
    for name, count in roadmap.additional.items():
        additional[name] = count
    # The vault counters appear only when it exposes at least one readable note:
    # a project with nothing in its vault answers exactly as before P07.
    if notes_total or notes:
        returned["notes"] = len(notes)
        additional["notes"] = notes_total - len(notes)
    unavailable_sections = ["roadmap"] if roadmap.unavailable else []
    if notes_unavailable:
        unavailable_sections.append("vault")
    return PreparedContext(
        project=project_ref,
        query_terms=terms,
        task=task,
        related_tasks=related,
        decisions=decisions,
        notes=notes,
        rules=rules,
        skills=skills,
        ai_work=ai_work,
        active_work=ActiveWork(claims=claims),
        roadmap=roadmap.item,
        roadmap_overview=roadmap.overview,
        unavailable=unavailable_sections,
        returned=returned,
        additional_available=additional,
        omitted_for_budget=dict(sorted(omitted.items())),
        limits=ContextLimits(
            limit=limit,
            max_chars=max_chars,
            chars_used=budget.used,
            item_text_cap=ITEM_TEXT_CAP,
            library_scan_capped=rules_capped or skills_capped,
            roadmap_scan_capped=roadmap.scan_capped,
        ),
    )
