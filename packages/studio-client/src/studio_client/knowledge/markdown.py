from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

import yaml

from studio_client.knowledge.memory import parse_note

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MARKDOWN_LINK = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^()<>\s]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_WIKILINK = re.compile(r"(!?)\[\[([^\[\]]+)\]\]")
_INLINE_CODE = re.compile(r"`[^`]*`")
_INLINE_TAG = re.compile(r"(?<![\w#/])#([A-Za-z][\w-]{0,63}(?:/[A-Za-z][\w-]{0,63})*)")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

_BARE_FRAGMENT = re.compile(r"^L(\d{1,7})(?:-L(\d{1,7}))?$")


class LinkKind(StrEnum):
    MARKDOWN = "markdown"
    WIKILINK = "wikilink"


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int
    slug: str


@dataclass(frozen=True)
class RawLink:
    """A link exactly as written, before any target resolution."""

    kind: LinkKind
    target: str
    label: str
    line: int
    embed: bool = False

    @property
    def path_part(self) -> str:
        return self.target.split("#", 1)[0].strip()

    @property
    def fragment(self) -> str | None:
        _, _, fragment = self.target.partition("#")
        return fragment.strip() or None


@dataclass(frozen=True)
class ParsedMarkdown:
    title: str
    body: str
    headings: tuple[Heading, ...]
    links: tuple[RawLink, ...]
    tags: tuple[str, ...]

    @property
    def first_heading_line(self) -> int | None:
        return self.headings[0].line if self.headings else None


def slugify(text: str) -> str:
    return _SLUG_STRIP.sub("-", text.strip().lower()).strip("-")


def _visible_lines(body: str) -> list[tuple[int, str]]:
    """Lines outside fenced code blocks, with their 1-based line number.

    Fenced blocks are stripped so headings, links and tags inside a code
    sample are never mistaken for real structure."""
    visible: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(body.splitlines(), start=1):
        match = _FENCE.match(line)
        if fence is None:
            if match is not None:
                fence = match.group(1)[0]
                continue
            visible.append((number, line))
        elif match is not None and match.group(1)[0] == fence:
            fence = None
    return visible


def _strip_inline_code(line: str) -> str:
    return _INLINE_CODE.sub(lambda match: " " * len(match.group(0)), line)


def _parse_links(visible: list[tuple[int, str]]) -> list[RawLink]:
    ordered: list[tuple[int, int, RawLink]] = []
    for number, raw_line in visible:
        line = _strip_inline_code(raw_line)
        for match in _WIKILINK.finditer(line):
            inner = match.group(2).strip()
            if not inner:
                continue
            target, _, label = inner.partition("|")
            ordered.append(
                (
                    number,
                    match.start(),
                    RawLink(
                        kind=LinkKind.WIKILINK,
                        target=target.strip(),
                        label=label.strip() or target.strip(),
                        line=number,
                        embed=match.group(1) == "!",
                    ),
                )
            )
        for match in _MARKDOWN_LINK.finditer(line):
            target = match.group(3).strip()
            if not target:
                continue
            ordered.append(
                (
                    number,
                    match.start(),
                    RawLink(
                        kind=LinkKind.MARKDOWN,
                        target=target,
                        label=match.group(2).strip() or target,
                        line=number,
                        embed=match.group(1) == "!",
                    ),
                )
            )
    ordered.sort(key=lambda item: (item[0], item[1]))
    return [link for _, _, link in ordered]


def _frontmatter_tags(frontmatter_tags: object) -> list[str]:
    if isinstance(frontmatter_tags, str):
        candidates = re.split(r"[,\s]+", frontmatter_tags)
    elif isinstance(frontmatter_tags, list):
        candidates = [str(item) for item in frontmatter_tags]
    else:
        return []
    tags: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip().lstrip("#").strip()
        if cleaned and re.fullmatch(r"[A-Za-z][\w/-]{0,63}", cleaned):
            tags.append(cleaned)
    return tags


def _parse_tags(visible: list[tuple[int, str]], frontmatter: dict[str, object]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for candidate in [*_frontmatter_tags(frontmatter.get("tags")), *_inline_tags(visible)]:
        if candidate not in seen:
            seen.add(candidate)
            tags.append(candidate)
    return tags


def _inline_tags(visible: list[tuple[int, str]]) -> list[str]:
    tags: list[str] = []
    for _, raw_line in visible:
        if _HEADING.match(raw_line):
            continue
        for match in _INLINE_TAG.finditer(_strip_inline_code(raw_line)):
            tags.append(match.group(1))
    return tags


def _frontmatter(text: str) -> dict[str, object]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    raw = text[3:end].strip()
    if not raw:
        return {}
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_markdown(text: str, fallback_title: str) -> ParsedMarkdown:
    """Split one Markdown document into the structure the index derives.

    Line numbers are relative to the original file (frontmatter included) so a
    `#L<line>` fragment points at the same line an editor would show. The body
    is returned verbatim: parsing never rewrites user content."""
    note = parse_note(text, fallback_title=fallback_title)
    offset = _line_offset(text, note.body)
    visible = [(offset + number, line) for number, line in _visible_lines(note.body)]
    headings: list[Heading] = []
    for number, line in visible:
        match = _HEADING.match(line)
        if match is not None:
            heading_text = match.group(2).strip()
            if heading_text:
                headings.append(
                    Heading(
                        level=len(match.group(1)),
                        text=heading_text,
                        line=number,
                        slug=slugify(heading_text),
                    )
                )
    return ParsedMarkdown(
        title=note.title,
        body=note.body,
        headings=tuple(headings),
        links=tuple(_parse_links(visible)),
        tags=tuple(_parse_tags(visible, _frontmatter(text))),
    )


def _line_offset(text: str, body: str) -> int:
    if not body:
        return 0
    index = text.find(body)
    if index < 0:
        return 0
    return text.count("\n", 0, index)


def parse_line_fragment(fragment: str | None) -> int | None:
    """A contract-shaped `L<line>` or `L<line>-L<line>` fragment, if any."""
    if not fragment:
        return None
    match = _BARE_FRAGMENT.match(fragment)
    if match is None:
        return None
    return int(match.group(1))
