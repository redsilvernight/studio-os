"""Pure three-way merge for Library text (roadmap P61a).

`merge_texts(base, ours, theirs)` reconciles two independent edits of the same
text against their common ancestor. It is pure: no I/O, no global state, no
mutation of its arguments, and the result depends only on the three inputs
(call order across invocations is irrelevant).

Contract:
- Line endings are normalised to LF before comparison and stay LF in the
  output, whatever mix of CRLF/LF the inputs use.
- Non-overlapping edits from both sides are applied without conflicts;
  identical edits made by both sides are applied once.
- Overlapping edits that differ become a structured `MergeConflict` and are
  rendered in `content` with git-style markers:
  `<<<<<<< ours`, `=======`, `>>>>>>> theirs`.
- A missing final newline is preserved for a clean merge. A conflicted block
  is always terminated so every marker stays on its own line.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

CONFLICT_START = "<<<<<<<"
CONFLICT_SEPARATOR = "======="
CONFLICT_END = ">>>>>>>"


@dataclass(frozen=True, slots=True)
class MergeConflict:
    """One unresolved block, positioned in both the merged output and the base.

    `start_line` is the 1-based line of the opening marker in `MergeResult.content`.
    `base_start`/`base_end` are 0-based half-open line indices into the normalised
    base text (the slice the two sides edited).
    """

    start_line: int
    base_start: int
    base_end: int
    base: str
    ours: str
    theirs: str


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Merged text plus, in output order, the structured unresolved blocks."""

    content: str
    conflicts: tuple[MergeConflict, ...]

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)


@dataclass(frozen=True, slots=True)
class _Change:
    start: int
    end: int
    lines: tuple[str, ...]


@dataclass(slots=True)
class _Region:
    start: int
    end: int


def merge_texts(
    base: str,
    ours: str,
    theirs: str,
    *,
    ours_label: str = "ours",
    theirs_label: str = "theirs",
) -> MergeResult:
    """Merge `ours` and `theirs`, both derived from `base`, deterministically."""
    _check_label(ours_label)
    _check_label(theirs_label)

    base_lines = _split_lines(_normalize(base))
    ours_lines = _split_lines(_normalize(ours))
    theirs_lines = _split_lines(_normalize(theirs))

    ours_changes = _changes(base_lines, ours_lines)
    theirs_changes = _changes(base_lines, theirs_lines)
    regions = _merge_regions(ours_changes, theirs_changes)

    chunks: list[str] = []
    conflicts: list[MergeConflict] = []
    emitted_newlines = 0
    position = 0
    for region in regions:
        chunks.extend(base_lines[position : region.start])
        emitted_newlines += region.start - position
        block = _render_region(base_lines, region, ours_changes, theirs_changes)
        if block is None:
            ours_text = _text(_render(base_lines, region.start, region.end, ours_changes))
            theirs_text = _text(_render(base_lines, region.start, region.end, theirs_changes))
            conflicts.append(
                MergeConflict(
                    start_line=emitted_newlines + 1,
                    base_start=region.start,
                    base_end=region.end,
                    base=_text(base_lines[region.start : region.end]),
                    ours=ours_text,
                    theirs=theirs_text,
                )
            )
            marker = _conflict_block(ours_text, theirs_text, ours_label, theirs_label)
            chunks.append(marker)
            emitted_newlines += marker.count("\n")
        else:
            chunks.extend(block)
            emitted_newlines += sum(line.count("\n") for line in block)
        position = region.end

    chunks.extend(base_lines[position:])
    return MergeResult(content="".join(chunks), conflicts=tuple(conflicts))


def _normalize(text: str) -> str:
    """Fold CRLF and lone CR to LF; the merge works on one line model."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_lines(text: str) -> list[str]:
    """Split on LF only, keeping terminators; the last line may be unterminated."""
    if not text:
        return []
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _text(lines: list[str] | tuple[str, ...]) -> str:
    return "".join(lines)


def _changes(base: list[str], side: list[str]) -> list[_Change]:
    matcher = difflib.SequenceMatcher(None, base, side, autojunk=False)
    changes: list[_Change] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            changes.append(_Change(start=i1, end=i2, lines=tuple(side[j1:j2])))
    return changes


def _spans_overlap(first_start: int, first_end: int, second_start: int, second_end: int) -> bool:
    """Half-open overlap, with insertions treated as a point.

    Two insertions at the same point collide. An insertion at the start of a
    replaced range collides (the order would be ambiguous); one at the end
    applies after it and does not.
    """
    first_is_point = first_start == first_end
    second_is_point = second_start == second_end
    if first_is_point and second_is_point:
        return first_start == second_start
    if first_is_point:
        return second_start <= first_start < second_end
    if second_is_point:
        return first_start <= second_start < first_end
    return max(first_start, second_start) < min(first_end, second_end)


def _merge_regions(first: list[_Change], second: list[_Change]) -> list[_Region]:
    spans = sorted((change.start, change.end) for change in (*first, *second))

    regions: list[_Region] = []
    for start, end in spans:
        if regions and _spans_overlap(regions[-1].start, regions[-1].end, start, end):
            regions[-1].start = min(regions[-1].start, start)
            regions[-1].end = max(regions[-1].end, end)
        else:
            regions.append(_Region(start=start, end=end))
    return regions


def _render(base: list[str], start: int, end: int, changes: list[_Change]) -> list[str]:
    """Apply the changes fully contained in `[start, end)` to the base slice."""
    rendered: list[str] = []
    position = start
    for change in changes:
        if not _contained(change, start, end):
            continue
        rendered.extend(base[position : change.start])
        rendered.extend(change.lines)
        position = change.end
    rendered.extend(base[position:end])
    return rendered


def _contained(change: _Change, start: int, end: int) -> bool:
    """A point insertion at the region's end belongs to the next region."""
    if change.start == change.end:
        if start == end:
            return change.start == start
        return start <= change.start < end
    return start <= change.start and change.end <= end


def _render_region(
    base: list[str], region: _Region, first: list[_Change], second: list[_Change]
) -> list[str] | None:
    """The agreed region text, or None when the two sides genuinely differ."""
    ours = _render(base, region.start, region.end, first)
    theirs = _render(base, region.start, region.end, second)
    base_slice = base[region.start : region.end]
    if ours == theirs:
        return ours
    if ours == base_slice:
        return theirs
    if theirs == base_slice:
        return ours
    return None


def _conflict_block(ours: str, theirs: str, ours_label: str, theirs_label: str) -> str:
    return (
        f"{CONFLICT_START} {ours_label}\n"
        f"{_terminated(ours)}"
        f"{CONFLICT_SEPARATOR}\n"
        f"{_terminated(theirs)}"
        f"{CONFLICT_END} {theirs_label}\n"
    )


def _terminated(text: str) -> str:
    if not text or text.endswith("\n"):
        return text
    return text + "\n"


def _check_label(label: str) -> None:
    if not label or "\n" in label or "\r" in label:
        raise ValueError("merge labels must be non-empty and single-line")
