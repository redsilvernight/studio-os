"""One-shot, replayable import of the historical decisions into the vault
(roadmap 63a26536, step P08, DEC-0187).

Two sources carry DEC numbers that were never kept in sync: the ADR files of
`docs/decisions/` and the server `decisions` table. Policy (DEC-0192):

- every ADR file keeps its number, and its content wins over the server row;
- a server row that shares its number with a *different* ADR (title
  similarity below `SAME_DECISION_RATIO`) is imported without a number, tagged
  `legacy-server-dec-NNNN`, and listed in the report — no number is reassigned;
- a server row with no file counterpart keeps its number;
- title/status gaps between a file and its server twin are reported, never
  merged automatically (TECH/09, "Resoudre une divergence depot/vault/base").

The planner (`plan_import`) is pure; `apply_plan` writes in one transaction
and is idempotent: a note already present (same number, or same slug for the
unnumbered ones) is never duplicated nor overwritten, only reported when its
content drifted. The decision sequence is then moved past every known number.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.vault import (
    VAULT_BODY_MAX,
    VAULT_SLUG_MAX,
    VAULT_SUMMARY_MAX,
    VAULT_TITLE_MAX,
    VaultActorType,
    VaultNoteStatus,
    VaultNoteType,
    VaultScope,
)

from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.vault import VaultNoteModel
from studio_api.services.vault import _append_version, _compute_hash
from studio_api.services.vault_secrets import scan as scan_secrets

SAME_DECISION_RATIO = 0.6
# Reviewed by hand on the P08 dry run (docs/DEC_IMPORT_P08.md): same decision
# on both sides despite a low title ratio (translation or rewording).
REVIEWED_SAME_DECISION = frozenset(
    {"DEC-0044", "DEC-0056", "DEC-0095", "DEC-0137", "DEC-0162", "DEC-0182"}
)
IMPORT_TAG = "dec-import"
CHANGE_SUMMARY = "import P08 (DEC-0192)"

_DEC_ID_RE = re.compile(r"^DEC-(\d{4,})$")
_TITLE_PREFIX_RE = re.compile(r"^DEC-\d{4,}\s*[—–:-]\s*")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s(.*))?$")
_HEADING_RE = re.compile(r"\A# .+?\n\n?")
# `scheme://user:password@` (e.g. the test DSN in DEC-0010): the vault secret
# scanner rejects any `user:x@` form, so the password is dropped (`user@host`)
# instead of dropping the note.
_URL_CREDENTIALS_RE = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@]+):[^\s@/]+@")
_URL_CREDENTIALS_MASK = r"\1@"

_FILE_STATUS = {
    "accepted": VaultNoteStatus.VALIDATED,
    "active": VaultNoteStatus.VALIDATED,
    "validated": VaultNoteStatus.VALIDATED,
    "proposed": VaultNoteStatus.PROPOSED,
    "superseded": VaultNoteStatus.SUPERSEDED,
}
_SERVER_STATUS = {
    "accepted": VaultNoteStatus.VALIDATED,
    "proposed": VaultNoteStatus.PROPOSED,
    "superseded": VaultNoteStatus.SUPERSEDED,
}


@dataclass(frozen=True)
class SourceDecision:
    readable_id: str
    title: str
    body: str
    raw_status: str | None
    project_id: uuid.UUID | None
    origin: str  # "file" | "server"
    path: str | None = None


@dataclass(frozen=True)
class PlannedNote:
    readable_id: str | None
    scope: VaultScope
    project_id: uuid.UUID | None
    slug: str
    title: str
    summary: str
    body: str
    status: VaultNoteStatus
    tags: tuple[str, ...]
    origin: str
    source_id: str


@dataclass(frozen=True)
class Finding:
    readable_id: str
    # collision | title | status | missing_status | redacted | skipped
    # | file_only | server_only
    kind: str
    detail: str


@dataclass
class ImportPlan:
    notes: list[PlannedNote] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    max_number: int = 0


@dataclass
class ApplyResult:
    created: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    drifted: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    next_number: int = 0


# ---------------------------------------------------------------- sources


def _unquote(value: str) -> str | None:
    value = value.strip()
    if value in ("", "null", "~"):
        return None
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return str(json.loads(value))
    return value


def parse_frontmatter(markdown: str) -> tuple[dict[str, str | None], str]:
    """Minimal reader for the flat front matter `scripts/adr_common.py`
    writes (scalars only, long values folded onto indented lines). The API
    image ships without PyYAML; a test pins this reader against yaml on every
    real ADR."""
    match = _FRONTMATTER_RE.match(markdown.replace("\r\n", "\n"))
    if match is None:
        raise ValueError("missing front matter")
    raw: dict[str, list[str]] = {}
    key: str | None = None
    for line in match.group(1).split("\n"):
        key_match = _KEY_RE.match(line)
        if key_match is not None and not line.startswith((" ", "\t")):
            key = key_match.group(1)
            raw[key] = [key_match.group(2) or ""]
        elif key is not None and line.strip():
            raw[key].append(line.strip())
    fields = {k: _unquote(" ".join(part for part in parts if part)) for k, parts in raw.items()}
    body = _HEADING_RE.sub("", match.group(2).strip(), count=1).strip()
    return fields, body


def load_file_decisions(
    decisions_dir: Path, project_id: uuid.UUID
) -> tuple[list[SourceDecision], list[Finding]]:
    decisions: list[SourceDecision] = []
    findings: list[Finding] = []
    for path in sorted(decisions_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        fields, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        readable_id = fields.get("server_readable_id") or fields.get("id")
        if readable_id is None or _DEC_ID_RE.match(readable_id) is None:
            findings.append(Finding(path.name, "skipped", "ADR sans identifiant DEC"))
            continue
        decisions.append(
            SourceDecision(
                readable_id=readable_id,
                title=fields.get("title") or readable_id,
                body=body,
                raw_status=fields.get("status"),
                project_id=project_id,
                origin="file",
                path=f"{decisions_dir.name}/{path.name}",
            )
        )
    return decisions, findings


async def load_server_decisions(session: AsyncSession) -> list[SourceDecision]:
    rows = (await session.execute(select(DecisionModel))).scalars().all()
    return [
        SourceDecision(
            readable_id=row.readable_id,
            title=row.title,
            body=row.body,
            raw_status=row.status,
            project_id=row.project_id,
            origin="server",
        )
        for row in rows
    ]


def load_server_snapshot(path: Path) -> list[SourceDecision]:
    """`docs/DEC_BASELINE_P00.json` (titles and statuses only): enough for a
    dry-run report without database access."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        SourceDecision(
            readable_id=entry["readable_id"],
            title=entry["title"],
            body="",
            raw_status=entry.get("status"),
            project_id=uuid.UUID(entry["project_id"]) if entry.get("project_id") else None,
            origin="server",
        )
        for entry in payload["decisions"]
    ]


# ---------------------------------------------------------------- planning


def _number(readable_id: str) -> int:
    match = _DEC_ID_RE.match(readable_id)
    return int(match.group(1)) if match else 0


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()


def clean_title(title: str) -> str:
    return _TITLE_PREFIX_RE.sub("", title.strip()).strip() or title.strip()


def _normalized(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _ascii(clean_title(title)).lower()).strip()


def title_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalized(a), _normalized(b)).ratio()


def _slug(prefix: str, readable_id: str, title: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", _ascii(clean_title(title)).lower()).strip("-")
    slug = f"{prefix}/{readable_id.lower()}-{words}" if words else f"{prefix}/{readable_id.lower()}"
    return slug[:VAULT_SLUG_MAX].rstrip("-_/")


def _summary(body: str) -> str:
    for block in re.split(r"\n\s*\n", body):
        stripped = block.strip()
        if stripped and not stripped.startswith(("#", "---", "|", "```")):
            collapsed = re.sub(r"\s+", " ", stripped)
            return collapsed[:VAULT_SUMMARY_MAX]
    return ""


def _scope(project_id: uuid.UUID | None) -> VaultScope:
    return VaultScope.PROJECT if project_id is not None else VaultScope.STUDIO


def _planned(
    source: SourceDecision,
    status: VaultNoteStatus,
    *,
    numbered: bool,
    extra_tags: tuple[str, ...] = (),
) -> PlannedNote:
    prefix = "decisions" if numbered else "decisions/legacy-server"
    title = clean_title(source.title)[:VAULT_TITLE_MAX]
    return PlannedNote(
        readable_id=source.readable_id if numbered else None,
        scope=_scope(source.project_id),
        project_id=source.project_id,
        slug=_slug(prefix, source.readable_id, source.title),
        title=title,
        summary=_summary(source.body),
        body=source.body or title,
        status=status,
        tags=(IMPORT_TAG, *extra_tags),
        origin=source.origin,
        source_id=source.path or source.readable_id,
    )


def plan_import(files: list[SourceDecision], server: list[SourceDecision]) -> ImportPlan:
    plan = ImportPlan()
    by_file = {d.readable_id: d for d in files}
    by_server = {d.readable_id: d for d in server}
    numbers = sorted(set(by_file) | set(by_server), key=_number)
    plan.max_number = max((_number(n) for n in numbers), default=0)

    for readable_id in numbers:
        file_dec = by_file.get(readable_id)
        server_dec = by_server.get(readable_id)
        server_status = (
            _SERVER_STATUS.get((server_dec.raw_status or "").lower(), VaultNoteStatus.PROPOSED)
            if server_dec is not None
            else None
        )
        if file_dec is not None:
            status = _FILE_STATUS.get((file_dec.raw_status or "").lower())
            if status is None:
                status = server_status or VaultNoteStatus.PROPOSED
                plan.findings.append(
                    Finding(
                        readable_id,
                        "missing_status",
                        f"statut fichier « {file_dec.raw_status} » → {status.value}"
                        + (" (serveur)" if server_status is not None else ""),
                    )
                )
            plan.notes.append(_planned(file_dec, status, numbered=True))
        if server_dec is None or server_status is None:
            plan.findings.append(
                Finding(readable_id, "file_only", file_dec.title if file_dec else "")
            )
            continue
        if file_dec is None:
            plan.notes.append(_planned(server_dec, server_status, numbered=True))
            plan.findings.append(Finding(readable_id, "server_only", clean_title(server_dec.title)))
            continue
        ratio = title_ratio(file_dec.title, server_dec.title)
        if ratio < SAME_DECISION_RATIO and readable_id not in REVIEWED_SAME_DECISION:
            legacy_tag = f"legacy-server-{readable_id.lower()}"
            plan.notes.append(
                _planned(server_dec, server_status, numbered=False, extra_tags=(legacy_tag,))
            )
            plan.findings.append(
                Finding(
                    readable_id,
                    "collision",
                    f"fichier « {clean_title(file_dec.title)} » ≠ serveur "
                    f"« {clean_title(server_dec.title)} » (ratio {ratio:.2f}) ; "
                    f"variante serveur importée sans numéro, tag {legacy_tag}",
                )
            )
            continue
        if _normalized(file_dec.title) != _normalized(server_dec.title):
            plan.findings.append(
                Finding(
                    readable_id,
                    "title",
                    f"fichier « {clean_title(file_dec.title)} » / serveur "
                    f"« {clean_title(server_dec.title)} »",
                )
            )
        file_status = plan.notes[-1].status
        if file_status is not server_status:
            plan.findings.append(
                Finding(
                    readable_id,
                    "status",
                    f"fichier {file_status.value} / serveur {server_status.value}",
                )
            )

    kept: list[PlannedNote] = []
    for note in plan.notes:
        redacted = _URL_CREDENTIALS_RE.sub(_URL_CREDENTIALS_MASK, note.body)
        if redacted != note.body:
            summary = _URL_CREDENTIALS_RE.sub(_URL_CREDENTIALS_MASK, note.summary)
            note = replace(note, body=redacted, summary=summary)
            plan.findings.append(
                Finding(
                    note.readable_id or note.source_id,
                    "redacted",
                    "mot de passe d'URL retiré (user@host)",
                )
            )
        problem = _rejection(note)
        if problem is None:
            kept.append(note)
        else:
            plan.findings.append(Finding(note.readable_id or note.source_id, "skipped", problem))
    plan.notes = kept
    return plan


def _rejection(note: PlannedNote) -> str | None:
    if len(note.body) > VAULT_BODY_MAX:
        return f"corps trop long ({len(note.body)} > {VAULT_BODY_MAX})"
    findings = scan_secrets({"title": note.title, "summary": note.summary, "body": note.body})
    if findings:
        patterns = ", ".join(sorted({f.pattern for f in findings}))
        return f"secret détecté ({patterns}) : à traiter à la main"
    return None


# ---------------------------------------------------------------- report

_KIND_TITLES = (
    ("collision", "Collisions de numéro (décisions différentes)"),
    ("title", "Titres divergents (même décision)"),
    ("status", "Statuts divergents"),
    ("missing_status", "Statuts fichier absents ou inconnus"),
    ("redacted", "Contenu masqué à l'import"),
    ("skipped", "Notes non importées"),
    ("file_only", "Présentes en fichier seulement"),
    ("server_only", "Présentes au serveur seulement"),
)


def render_report(plan: ImportPlan, result: ApplyResult | None = None) -> str:
    numbered = sum(1 for n in plan.notes if n.readable_id is not None)
    lines = [
        "# Import P08 — rapport de divergences DEC (fichiers ↔ serveur)",
        "",
        "Politique : DEC-0192. Le contenu de l'ADR fichier fait foi ; aucune "
        "divergence n'est fusionnée automatiquement.",
        "",
        "Rejouer : `studio-admin vault import-decisions --decisions-dir docs/decisions "
        "--project <projet> [--server-snapshot docs/DEC_BASELINE_P00.json | "
        "--apply --author-email <admin>] [--report <fichier>]`.",
        "",
        f"- Notes planifiées : **{len(plan.notes)}** ({numbered} numérotées, "
        f"{len(plan.notes) - numbered} variantes serveur sans numéro)",
        f"- Numéro max connu : **DEC-{plan.max_number:04d}**",
    ]
    if result is not None:
        lines += [
            f"- Créées : {len(result.created)} ; inchangées : {len(result.unchanged)} ; "
            f"dérivées (non écrasées) : {len(result.drifted)} ; "
            f"conflits : {len(result.conflicts)}",
            f"- Prochain numéro délivré : DEC-{result.next_number:04d}",
        ]
    for kind, heading in _KIND_TITLES:
        items = [f for f in plan.findings if f.kind == kind]
        lines += ["", f"## {heading} ({len(items)})", ""]
        lines += [f"- `{f.readable_id}` : {f.detail}" for f in items] or ["Aucune."]
    if result is not None and (result.drifted or result.conflicts):
        lines += ["", "## À relire après application", ""]
        lines += [f"- dérive : {item}" for item in result.drifted]
        lines += [f"- conflit : {item}" for item in result.conflicts]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- apply


async def _existing(session: AsyncSession, note: PlannedNote) -> VaultNoteModel | None:
    if note.readable_id is not None:
        query = select(VaultNoteModel).where(VaultNoteModel.readable_id == note.readable_id)
    else:
        query = select(VaultNoteModel).where(
            VaultNoteModel.scope == note.scope.value,
            VaultNoteModel.slug == note.slug,
            VaultNoteModel.status != VaultNoteStatus.ARCHIVED.value,
        )
        if note.project_id is not None:
            query = query.where(VaultNoteModel.project_id == note.project_id)
    return (await session.execute(query)).scalars().first()


async def _slug_taken(session: AsyncSession, note: PlannedNote) -> bool:
    query = select(VaultNoteModel.id).where(
        VaultNoteModel.scope == note.scope.value,
        VaultNoteModel.slug == note.slug,
        VaultNoteModel.status != VaultNoteStatus.ARCHIVED.value,
    )
    if note.project_id is not None:
        query = query.where(VaultNoteModel.project_id == note.project_id)
    return (await session.execute(query)).first() is not None


async def _max_number(session: AsyncSession, column: Any) -> int:
    value = (
        await session.execute(
            select(func.max(cast(func.substring(column, 5), Integer))).where(
                column.op("~")(r"^DEC-[0-9]+$")
            )
        )
    ).scalar_one_or_none()
    return int(value or 0)


async def _advance_sequence(session: AsyncSession, floor: int) -> int:
    """Move `decisions_readable_id_seq` so the next `nextval` exceeds every
    number in use (files, decisions table, vault). Never moves it backwards."""
    decision_max = await _max_number(session, DecisionModel.readable_id)
    vault_max = await _max_number(session, VaultNoteModel.readable_id)
    highest = max(floor, decision_max, vault_max)
    last_value, is_called = (
        await session.execute(text("SELECT last_value, is_called FROM decisions_readable_id_seq"))
    ).one()
    next_value = last_value + 1 if is_called else last_value
    if next_value <= highest:
        await session.execute(
            text("SELECT setval('decisions_readable_id_seq', :value, true)"), {"value": highest}
        )
        next_value = highest + 1
    return int(next_value)


async def apply_plan(session: AsyncSession, plan: ImportPlan, author_id: uuid.UUID) -> ApplyResult:
    result = ApplyResult()
    for planned in plan.notes:
        label = planned.readable_id or planned.slug
        content_hash = _compute_hash(
            planned.title,
            planned.summary,
            planned.body,
            planned.status.value,
            list(planned.tags),
            [],
            [],
        )
        existing = await _existing(session, planned)
        if existing is not None:
            if existing.content_hash == content_hash:
                result.unchanged.append(label)
            else:
                result.drifted.append(f"{label} (note {existing.id}, contenu différent)")
            continue
        if await _slug_taken(session, planned):
            result.conflicts.append(f"{label} : slug {planned.slug} déjà pris")
            continue
        note = VaultNoteModel(
            scope=planned.scope.value,
            project_id=planned.project_id,
            slug=planned.slug,
            readable_id=planned.readable_id,
            note_type=VaultNoteType.DECISION.value,
            title=planned.title,
            summary=planned.summary,
            body=planned.body,
            status=planned.status.value,
            tags=list(planned.tags),
            anchors=[],
            content_hash=content_hash,
            author_type=VaultActorType.SYSTEM.value,
            author_id=author_id,
        )
        session.add(note)
        await session.flush()
        await _append_version(session, note, [], CHANGE_SUMMARY)
        result.created.append(label)
    result.next_number = await _advance_sequence(session, plan.max_number)
    await session.commit()
    return result
