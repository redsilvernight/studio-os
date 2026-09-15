from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.scope import ScopePolicy

DEFAULT_MAX_RESULTS = 20
DEFAULT_EXCERPT_CHARS = 500
DEFAULT_READ_CHARS = 4000


@dataclass(frozen=True)
class MemoryNoteHit:
    path: str
    title: str
    excerpt: str
    truncated: bool = False


@dataclass(frozen=True)
class MemorySearchResult:
    matches: list[MemoryNoteHit] = field(default_factory=list)
    reason: str | None = None


@dataclass(frozen=True)
class MemoryReadResult:
    path: str
    title: str
    content: str
    truncated: bool = False


class MemoryProposal(dict[str, object]):
    """Placeholder shape for a future memory write proposal (8.4/8.5)."""


class MemoryProvider(Protocol):
    """`TECH/09` memory surface, read-only for 8.2 (DEC-0042).

    Write methods are declared so the `TECH/09` names freeze now, but their
    approval loop crosses the server and belongs to 8.4/8.5.
    """

    def search(
        self, query: str, *, max_results: int = DEFAULT_MAX_RESULTS
    ) -> MemorySearchResult: ...
    def read(self, path: str, *, max_chars: int = DEFAULT_READ_CHARS) -> MemoryReadResult: ...
    def propose(self, proposal: MemoryProposal) -> object: ...
    def write_if_authorized(self, proposal: MemoryProposal) -> object: ...
    def append_task_log(self, entry: dict[str, object]) -> object: ...
    def create_decision_note(self, note: dict[str, object]) -> object: ...


@dataclass(frozen=True)
class _ParsedNote:
    title: str
    body: str


def parse_note(text: str, fallback_title: str) -> _ParsedNote:
    """Split YAML frontmatter from body. Raises `INVALID_FRONTMATTER` on a
    malformed header — the caller decides between skipping (search) and
    failing loudly (direct read)."""
    body = text
    title = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end == -1:
            raise KnowledgeError(
                KnowledgeError.INVALID_FRONTMATTER, "unterminated frontmatter block"
            )
        raw = text[3:end].strip()
        try:
            frontmatter = yaml.safe_load(raw) if raw else {}
        except yaml.YAMLError as exc:
            raise KnowledgeError(
                KnowledgeError.INVALID_FRONTMATTER, f"frontmatter is not valid YAML: {exc}"
            ) from exc
        if not isinstance(frontmatter, dict):
            raise KnowledgeError(
                KnowledgeError.INVALID_FRONTMATTER, "frontmatter must be a mapping"
            )
        candidate = frontmatter.get("title")
        if isinstance(candidate, str) and candidate.strip():
            title = candidate.strip()
        body = text[end + 4 :].lstrip("\n")
    if not title:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                break
    return _ParsedNote(title=title or fallback_title, body=body)


def make_excerpt(body: str, needle: str, max_chars: int) -> tuple[str, bool]:
    """Window around the first match, truncated — never a full-note dump."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    flat = " ".join(body.split())
    if len(flat) <= max_chars:
        return flat, False
    index = flat.lower().find(needle.lower()) if needle else -1
    start = max(0, index - 160) if index >= 0 else 0
    window = flat[start : start + max_chars]
    prefix = "…" if start > 0 else ""
    truncated = start > 0 or start + max_chars < len(flat)
    suffix = "…" if start + max_chars < len(flat) else ""
    return f"{prefix}{window}{suffix}", truncated


class VaultMemoryProvider:
    """Read-only vault adapter: `search` + `read` over the exposed scope.

    Never touches the network, never writes. Out-of-scope paths raise
    `OUT_OF_SCOPE` even when addressed by exact path; unparsable notes are
    skipped by `search` but fail loudly on direct `read`.
    """

    def __init__(
        self,
        vault_root: Path | None,
        scope: ScopePolicy | None = None,
        *,
        max_results: int = DEFAULT_MAX_RESULTS,
        excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
    ) -> None:
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        if excerpt_chars <= 0:
            raise ValueError("excerpt_chars must be positive")
        self._vault_root = vault_root
        self._scope = scope or ScopePolicy()
        self._max_results = max_results
        self._excerpt_chars = excerpt_chars

    def _root(self) -> Path:
        if self._vault_root is None:
            raise KnowledgeError(KnowledgeError.VAULT_MISSING, "no vault path configured")
        root = self._vault_root
        if not root.exists():
            raise KnowledgeError(KnowledgeError.VAULT_MISSING, f"vault not found: {root}")
        if not root.is_dir():
            raise KnowledgeError(
                KnowledgeError.VAULT_NOT_A_DIRECTORY, f"vault is not a directory: {root}"
            )
        return root

    def search(self, query: str, *, max_results: int | None = None) -> MemorySearchResult:
        """Case-insensitive substring search over exposed notes, bounded."""
        limit = max_results if max_results is not None else self._max_results
        if limit <= 0:
            raise ValueError("max_results must be positive")
        try:
            root = self._root()
        except KnowledgeError as exc:
            return MemorySearchResult(matches=[], reason=exc.reason)
        needle = query.strip().lower()
        if not needle:
            return MemorySearchResult(matches=[])
        hits: list[MemoryNoteHit] = []
        for path in self._scope.exposed_files(root):
            if len(hits) >= limit:
                break
            try:
                note = parse_note(path.read_text(encoding="utf-8"), fallback_title=path.stem)
            except (OSError, UnicodeDecodeError, KnowledgeError):
                continue
            haystack = f"{note.title}\n{note.body}".lower()
            if needle not in haystack:
                continue
            excerpt, truncated = make_excerpt(note.body, needle, self._excerpt_chars)
            hits.append(
                MemoryNoteHit(
                    path=path.resolve().relative_to(root).as_posix(),
                    title=note.title,
                    excerpt=excerpt,
                    truncated=truncated,
                )
            )
        return MemorySearchResult(matches=hits)

    def read(self, path: str, *, max_chars: int = DEFAULT_READ_CHARS) -> MemoryReadResult:
        """Read one in-scope note, truncated — never an unbounded dump."""
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        root = self._root()
        resolved = self._scope.resolve(root, path)
        if not resolved.exists():
            raise KnowledgeError(KnowledgeError.NOT_FOUND, f"note not found: {path!r}")
        if not resolved.is_file():
            raise KnowledgeError(KnowledgeError.NOT_A_FILE, f"not a file: {path!r}")
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise KnowledgeError(KnowledgeError.NOT_FOUND, f"note unreadable: {path!r}") from exc
        except UnicodeDecodeError as exc:
            raise KnowledgeError(
                KnowledgeError.INVALID_FRONTMATTER, f"note is not UTF-8 text: {path!r}"
            ) from exc
        note = parse_note(text, fallback_title=resolved.stem)
        content, truncated = make_excerpt(note.body, "", max_chars)
        return MemoryReadResult(
            path=resolved.relative_to(root).as_posix(),
            title=note.title,
            content=content,
            truncated=truncated,
        )

    def propose(self, proposal: MemoryProposal) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "memory writes need the server approval loop (8.4/8.5), not this read-only adapter",
        )

    def write_if_authorized(self, proposal: MemoryProposal) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "memory writes need the server approval loop (8.4/8.5), not this read-only adapter",
        )

    def append_task_log(self, entry: dict[str, object]) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "memory writes need the server approval loop (8.4/8.5), not this read-only adapter",
        )

    def create_decision_note(self, note: dict[str, object]) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "memory writes need the server approval loop (8.4/8.5), not this read-only adapter",
        )
