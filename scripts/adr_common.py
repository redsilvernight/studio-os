"""Shared, dependency-light helpers for the DECISIONS.md -> unit-ADR
migration (Phase 4) and the vault sync / decision-graph bridge that build on
top of it (Phases 5-6).

Parsing `docs/DECISIONS.md` and building an ADR's front matter is pure and
deterministic: same source bytes in, same output every time -- required for
the migration and the index generator to be idempotent (mandate: "deuxieme
execution sans diff").
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEC_HEADING_RE = re.compile(r"^## (DEC-\d{4}) — (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class ParsedDecision:
    id: str  # "DEC-0001"
    title: str  # full heading text after the id, e.g. "Layout du depot : ..."
    body: str  # raw markdown, trimmed, verbatim from the source


@dataclass(frozen=True)
class ParsedLog:
    preamble: str  # everything before the first "## DEC-" heading, trimmed
    decisions: list[ParsedDecision]


def parse_decisions_log(text: str) -> ParsedLog:
    """Split `docs/DECISIONS.md` into its preamble and one entry per
    `## DEC-XXXX — Title` heading. Raises ValueError on a duplicate id --
    the source is expected to already be unique; migration must not paper
    over that."""
    matches = list(DEC_HEADING_RE.finditer(text))
    preamble = text[: matches[0].start()].strip() if matches else text.strip()

    seen: set[str] = set()
    decisions: list[ParsedDecision] = []
    for i, m in enumerate(matches):
        dec_id, title = m.group(1), m.group(2).strip()
        if dec_id in seen:
            raise ValueError(f"duplicate id in source log: {dec_id}")
        seen.add(dec_id)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        decisions.append(ParsedDecision(id=dec_id, title=title, body=body))
    return ParsedLog(preamble=preamble, decisions=decisions)


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def slugify(title: str, *, max_len: int = 60) -> str:
    """Deterministic, readable slug for an ADR filename. Drops anything in
    backticks/parens content markers, lowercases, collapses runs of
    non-alphanumerics to one hyphen, trims to max_len at a hyphen boundary."""
    cleaned = title.replace("`", "").replace(":", " ")
    slug = _SLUG_STRIP_RE.sub("-", cleaned.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) <= max_len:
        return slug
    truncated = slug[:max_len]
    if "-" in truncated:
        truncated = truncated.rsplit("-", 1)[0]
    return truncated


def adr_filename(dec_id: str, title: str) -> str:
    return f"{dec_id}-{slugify(title)}.md"


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- vault lookup --------------------------------------------------------

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class VaultNote:
    path: Path
    frontmatter: dict[str, Any]
    body: str


def load_vault_note(path: Path) -> VaultNote | None:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    fm = yaml.safe_load(m.group(1)) or {}
    return VaultNote(path=path, frontmatter=fm, body=m.group(2))


def index_vault_notes_by_dec_id(vault_decisions_dir: Path) -> dict[str, VaultNote]:
    """Map "DEC-XXXX" -> its vault note, using the note's `aliases` list
    (falls back to none if a note has no DEC-XXXX alias -- never guessed)."""
    index: dict[str, VaultNote] = {}
    if not vault_decisions_dir.exists():
        return index
    for path in sorted(vault_decisions_dir.glob("*.md")):
        note = load_vault_note(path)
        if note is None:
            continue
        for alias in note.frontmatter.get("aliases", []) or []:
            if isinstance(alias, str) and re.fullmatch(r"DEC-\d{4}", alias):
                index[alias] = note
    return index


# --- ADR front matter ------------------------------------------------------

ADR_FIELD_ORDER = [
    "id",
    "title",
    "status",
    "date",
    "author",
    "supersedes",
    "superseded_by",
    "source",
    "sync_hash",
    "graphify_entities",
]


def build_adr_frontmatter(
    *,
    dec_id: str,
    title: str,
    source: str,
    sync_hash: str,
    vault_note: VaultNote | None,
) -> dict[str, Any]:
    """Only include a field when its value is actually known -- from the
    source log (id/title/source/sync_hash, always known) or from a matching
    vault note (status/date/author/supersedes/superseded_by/graphify
    entities, already curated there). Never fabricate a value for a field
    with no known source."""
    fields: dict[str, Any] = {"id": dec_id, "title": title}
    fm = vault_note.frontmatter if vault_note is not None else {}

    if "status" in fm:
        fields["status"] = fm["status"]
    if "created" in fm:
        # PyYAML parses an unquoted `created: 2026-09-12` as datetime.date,
        # not str -- normalize so every ADR's `date` field is the same
        # portable string type regardless of how the vault note wrote it.
        fields["date"] = str(fm["created"])
    if fm.get("author"):
        fields["author"] = fm["author"]
    # supersedes/superseded_by: vault stores superseded_by explicitly
    # (including an explicit `null` meaning "not superseded", which IS a
    # known value, not an absent one) -- carry it through as-is.
    if "superseded_by" in fm:
        fields["superseded_by"] = fm["superseded_by"]
    if "supersedes" in fm:
        fields["supersedes"] = fm["supersedes"]

    fields["source"] = source
    fields["sync_hash"] = sync_hash

    entities = (
        fm.get("graphify", {}).get("entities") if isinstance(fm.get("graphify"), dict) else None
    )
    if entities:
        fields["graphify_entities"] = entities

    return fields


def render_adr_markdown(fields: dict[str, Any], body: str) -> str:
    ordered = {k: fields[k] for k in ADR_FIELD_ORDER if k in fields}
    frontmatter = yaml.safe_dump(
        ordered, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return f"---\n{frontmatter}---\n\n# {fields['id']} — {fields['title']}\n\n{body}\n"


_HEADING_RE = re.compile(r"\A# .+?\n\n?")


def parse_adr_markdown(text: str) -> tuple[dict[str, Any], str]:
    """Inverse of render_adr_markdown: returns (fields, body) where body is
    the original prose, with the "# ID — Title" heading render_adr_markdown
    prepends stripped back off (so migration's lossless check can compare
    this body directly against the source log's parsed body)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("not a valid ADR file: missing front matter")
    fields = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).strip()
    body = _HEADING_RE.sub("", body, count=1).strip()
    return fields, body
