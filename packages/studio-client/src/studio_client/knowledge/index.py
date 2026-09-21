from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from studio_contracts.local.common import LocalResourceKind, build_local_uri, parse_local_uri
from studio_contracts.local.graph import NodeKind, RelationKind
from studio_contracts.local.provider import IndexState

from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.markdown import LinkKind, RawLink, parse_markdown, slugify
from studio_client.knowledge.vault import (
    DEFAULT_EXCLUDE_GLOBS,
    DEFAULT_INCLUDE_GLOBS,
    VaultFile,
    content_hash,
    iter_markdown,
    vault_fingerprint,
)

INDEX_SCHEMA_VERSION = 1
INDEX_FILENAME = "knowledge-index.sqlite3"
MAX_SNIPPET_CHARS = 300
MAX_DOCUMENTS = 5_000

DOC_NODE_PREFIX = "doc"
HEADING_NODE_PREFIX = "heading"
TAG_NODE_PREFIX = "tag"
EDGE_PREFIX = "edge"

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        uri TEXT PRIMARY KEY,
        relative_path TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL,
        modified_at TEXT NOT NULL,
        body TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS headings (
        document_uri TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        level INTEGER NOT NULL,
        text TEXT NOT NULL,
        slug TEXT NOT NULL,
        line INTEGER NOT NULL,
        PRIMARY KEY (document_uri, ordinal)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS links (
        document_uri TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        kind TEXT NOT NULL,
        embed INTEGER NOT NULL,
        target TEXT NOT NULL,
        resolved_kind TEXT,
        resolved_node_id TEXT,
        resolved_uri TEXT,
        PRIMARY KEY (document_uri, ordinal)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tags (
        document_uri TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        tag TEXT NOT NULL,
        slug TEXT NOT NULL,
        PRIMARY KEY (document_uri, ordinal)
    )
    """,
)


@dataclass(frozen=True)
class IndexSnapshot:
    state: IndexState
    built_at: datetime | None = None
    source_fingerprint: str | None = None
    item_count: int | None = None
    progress_percent: int | None = None


@dataclass(frozen=True)
class IndexedDocument:
    uri: str
    relative_path: str
    title: str
    content_hash: str
    size_bytes: int
    modified_at: datetime
    outgoing: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class IndexedHit:
    uri: str
    relative_path: str
    title: str
    content_hash: str
    modified_at: datetime
    score: float
    snippet: str


@dataclass(frozen=True)
class GraphNodeRow:
    node_id: str
    kind: NodeKind
    label: str
    uri: str | None
    extractor: str
    evidence_uri: str | None


@dataclass(frozen=True)
class GraphEdgeRow:
    edge_id: str
    kind: RelationKind
    source_node_id: str
    target_node_id: str
    extractor: str
    evidence_uri: str | None


@dataclass(frozen=True)
class GraphSnapshot:
    nodes: tuple[GraphNodeRow, ...]
    edges: tuple[GraphEdgeRow, ...]


@dataclass(frozen=True)
class _ResolvedLink:
    kind: str | None
    node_id: str | None
    uri: str | None


class KnowledgeIndex:
    """Derived, deletable, rebuildable local index over canonical Markdown.

    The SQLite file lives in the daemon's own cache directory. Deleting it loses
    nothing: every row is recomputed from the vault. No content ever leaves the
    machine — this module has no network code path at all."""

    def __init__(
        self,
        root: Path,
        *,
        workspace_id: UUID,
        include_globs: Sequence[str] = DEFAULT_INCLUDE_GLOBS,
        exclude_globs: Sequence[str] = DEFAULT_EXCLUDE_GLOBS,
        max_documents: int = MAX_DOCUMENTS,
    ) -> None:
        if max_documents <= 0:
            raise ValueError("max_documents must be positive")
        self._root = root
        self._workspace_id = workspace_id
        self._include_globs = tuple(include_globs)
        self._exclude_globs = tuple(exclude_globs)
        self._max_documents = max_documents

    @property
    def directory(self) -> Path:
        return self._root

    @property
    def path(self) -> Path:
        return self._root / INDEX_FILENAME

    def exists(self) -> bool:
        return self.path.is_file()

    def drop(self) -> bool:
        """Remove the derived index only. Canonical Markdown is never touched."""
        removed = False
        for candidate in self._root.glob(f"{INDEX_FILENAME}*"):
            if candidate.is_file():
                candidate.unlink()
                removed = True
        return removed

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        for statement in _SCHEMA:
            connection.execute(statement)

    def _meta(self, connection: sqlite3.Connection, key: str) -> str | None:
        row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _set_meta(self, connection: sqlite3.Connection, **values: str | int | None) -> None:
        for key, value in values.items():
            connection.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, "" if value is None else str(value)),
            )

    def _counts(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT COUNT(*) AS total FROM documents").fetchone()
        return 0 if row is None else int(row["total"])

    def snapshot(self, vault_root: Path) -> IndexSnapshot:
        """Current derived state, computed against the live vault fingerprint."""
        if not self.exists():
            return IndexSnapshot(state=IndexState.ABSENT)
        try:
            connection = self._connect()
        except sqlite3.Error as exc:
            raise KnowledgeError(KnowledgeError.INDEX_CORRUPT, "index cannot be opened") from exc
        try:
            version = self._meta(connection, "schema_version")
            if version != str(INDEX_SCHEMA_VERSION):
                return IndexSnapshot(state=IndexState.CORRUPT)
            if self._meta(connection, "indexing") == "1":
                progress = self._meta(connection, "progress_percent")
                return IndexSnapshot(
                    state=IndexState.INDEXING,
                    progress_percent=int(progress) if progress else None,
                )
            built_at = self._meta(connection, "built_at")
            if not built_at:
                return IndexSnapshot(state=IndexState.ABSENT)
            fingerprint = self._meta(connection, "source_fingerprint")
            current = vault_fingerprint(
                vault_root,
                include_globs=self._include_globs,
                exclude_globs=self._exclude_globs,
            )
            state = IndexState.READY if fingerprint == current else IndexState.STALE
            return IndexSnapshot(
                state=state,
                built_at=datetime.fromisoformat(built_at),
                source_fingerprint=fingerprint,
                item_count=self._counts(connection),
            )
        except sqlite3.DatabaseError:
            return IndexSnapshot(state=IndexState.CORRUPT)
        finally:
            connection.close()

    def rebuild(
        self,
        vault_root: Path,
        *,
        full: bool,
        progress: Callable[[int], None] | None = None,
        now: datetime | None = None,
    ) -> IndexSnapshot:
        """Reindex the vault. `full` drops every derived row first; the
        incremental mode only rewrites documents whose content changed."""
        if not vault_root.is_dir():
            raise KnowledgeError(KnowledgeError.VAULT_MISSING, "the vault folder is missing")
        self._root.mkdir(parents=True, exist_ok=True)
        stamp = now or datetime.now(UTC)
        if full:
            self.drop()
        files = list(
            iter_markdown(
                vault_root,
                include_globs=self._include_globs,
                exclude_globs=self._exclude_globs,
            )
        )[: self._max_documents]
        connection = self._connect()
        try:
            self._create_schema(connection)
            self._set_meta(
                connection,
                schema_version=INDEX_SCHEMA_VERSION,
                indexing=1,
                progress_percent=0,
                built_at="",
                source_fingerprint="",
            )
            connection.commit()
            try:
                self._fill(connection, files, full=full, progress=progress)
            except BaseException:
                self._set_meta(connection, indexing=0, progress_percent=None)
                connection.commit()
                raise
            self._set_meta(
                connection,
                indexing=0,
                progress_percent=None,
                built_at=stamp.isoformat(),
                source_fingerprint=vault_fingerprint(
                    vault_root,
                    include_globs=self._include_globs,
                    exclude_globs=self._exclude_globs,
                ),
                item_count=self._counts(connection),
            )
            connection.commit()
        finally:
            connection.close()
        return self.snapshot(vault_root)

    def _fill(
        self,
        connection: sqlite3.Connection,
        files: Sequence[VaultFile],
        *,
        full: bool,
        progress: Callable[[int], None] | None,
    ) -> None:
        known = {
            str(row["relative_path"])
            for row in connection.execute("SELECT relative_path FROM documents")
        }
        present: set[str] = set()
        total = max(len(files), 1)
        for position, item in enumerate(files, start=1):
            present.add(item.relative_path)
            self._index_file(connection, item, full=full)
            percent = int(position * 100 / total)
            self._set_meta(connection, progress_percent=percent)
            connection.commit()
            if progress is not None:
                progress(percent)
        for stale_path in sorted(known - present):
            self._delete_document(connection, stale_path)
        self._resolve_links(connection)

    def _index_file(self, connection: sqlite3.Connection, item: VaultFile, *, full: bool) -> None:
        try:
            text = item.absolute_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            self._delete_document(connection, item.relative_path)
            return
        digest = content_hash(text)
        if not full:
            row = connection.execute(
                "SELECT content_hash, mtime_ns FROM documents WHERE relative_path = ?",
                (item.relative_path,),
            ).fetchone()
            if (
                row is not None
                and str(row["content_hash"]) == digest
                and int(row["mtime_ns"]) == item.mtime_ns
            ):
                return
        try:
            uri = build_local_uri(
                LocalResourceKind.KNOWLEDGE, self._workspace_id, item.relative_path
            )
            parsed = parse_markdown(text, fallback_title=Path(item.relative_path).stem)
        except (ValueError, KnowledgeError):
            self._delete_document(connection, item.relative_path)
            return
        self._delete_document(connection, item.relative_path)
        modified_at = datetime.fromtimestamp(item.mtime_ns / 1_000_000_000, tz=UTC)
        connection.execute(
            "INSERT INTO documents "
            "(uri, relative_path, title, content_hash, size_bytes, mtime_ns, modified_at, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uri,
                item.relative_path,
                parsed.title,
                digest,
                item.size_bytes,
                item.mtime_ns,
                modified_at.isoformat(),
                parsed.body,
            ),
        )
        for ordinal, heading in enumerate(parsed.headings):
            connection.execute(
                "INSERT INTO headings (document_uri, ordinal, level, text, slug, line) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uri, ordinal, heading.level, heading.text, heading.slug, heading.line),
            )
        for ordinal, link in enumerate(parsed.links):
            connection.execute(
                "INSERT INTO links (document_uri, ordinal, kind, embed, target) "
                "VALUES (?, ?, ?, ?, ?)",
                (uri, ordinal, link.kind.value, 1 if link.embed else 0, link.target),
            )
        for ordinal, tag in enumerate(parsed.tags):
            connection.execute(
                "INSERT INTO tags (document_uri, ordinal, tag, slug) VALUES (?, ?, ?, ?)",
                (uri, ordinal, tag, tag_slug(tag)),
            )

    def _delete_document(self, connection: sqlite3.Connection, relative_path: str) -> None:
        row = connection.execute(
            "SELECT uri FROM documents WHERE relative_path = ?", (relative_path,)
        ).fetchone()
        if row is None:
            return
        uri = str(row["uri"])
        for table in ("headings", "links", "tags"):
            connection.execute(f"DELETE FROM {table} WHERE document_uri = ?", (uri,))
        connection.execute("DELETE FROM documents WHERE uri = ?", (uri,))

    def _resolve_links(self, connection: sqlite3.Connection) -> None:
        by_path: dict[str, str] = {}
        for row in connection.execute("SELECT uri, relative_path FROM documents"):
            by_path[str(row["relative_path"]).casefold()] = str(row["uri"])
        by_line: dict[tuple[str, int], str] = {}
        by_slug: dict[tuple[str, str], tuple[str, int]] = {}
        for row in connection.execute("SELECT document_uri, slug, line FROM headings"):
            uri = str(row["document_uri"])
            line = int(row["line"])
            by_line[(uri, line)] = heading_node_id(uri, line)
            by_slug[(uri, str(row["slug"]))] = (heading_node_id(uri, line), line)
        for row in connection.execute(
            "SELECT document_uri, ordinal, kind, embed, target FROM links"
        ):
            document_uri = str(row["document_uri"])
            resolved = self._resolve_one(
                document_uri,
                RawLink(
                    kind=LinkKind(str(row["kind"])),
                    target=str(row["target"]),
                    label="",
                    line=0,
                    embed=int(row["embed"]) == 1,
                ),
                by_path=by_path,
                by_line=by_line,
                by_slug=by_slug,
            )
            connection.execute(
                "UPDATE links SET resolved_kind = ?, resolved_node_id = ?, resolved_uri = ? "
                "WHERE document_uri = ? AND ordinal = ?",
                (resolved.kind, resolved.node_id, resolved.uri, document_uri, int(row["ordinal"])),
            )

    def _resolve_one(
        self,
        document_uri: str,
        link: RawLink,
        *,
        by_path: dict[str, str],
        by_line: dict[tuple[str, int], str],
        by_slug: dict[tuple[str, str], tuple[str, int]],
    ) -> _ResolvedLink:
        path_part = link.path_part
        fragment = link.fragment
        if path_part and _looks_external(path_part):
            return _ResolvedLink(None, None, None)
        if not path_part:
            return self._resolve_anchor(document_uri, fragment, by_line, by_slug)
        target_uri = self._resolve_path(document_uri, path_part, by_path)
        if target_uri is None:
            return _ResolvedLink(None, None, None)
        if link.embed:
            return _ResolvedLink(NodeKind.DOCUMENT.value, doc_node_id(target_uri), target_uri)
        return self._resolve_anchor(target_uri, fragment, by_line, by_slug)

    def _resolve_anchor(
        self,
        document_uri: str,
        fragment: str | None,
        by_line: dict[tuple[str, int], str],
        by_slug: dict[tuple[str, str], tuple[str, int]],
    ) -> _ResolvedLink:
        if fragment:
            line = _line_fragment(fragment)
            if line is not None and (document_uri, line) in by_line:
                return _ResolvedLink(
                    NodeKind.HEADING.value,
                    by_line[(document_uri, line)],
                    self._heading_uri(document_uri, line),
                )
            slug = slugify(fragment)
            if slug and (document_uri, slug) in by_slug:
                node_id, heading_line = by_slug[(document_uri, slug)]
                return _ResolvedLink(
                    NodeKind.HEADING.value, node_id, self._heading_uri(document_uri, heading_line)
                )
        return _ResolvedLink(NodeKind.DOCUMENT.value, doc_node_id(document_uri), document_uri)

    def _heading_uri(self, document_uri: str, line: int) -> str:
        return build_local_uri(
            LocalResourceKind.KNOWLEDGE,
            self._workspace_id,
            parse_local_uri(document_uri)[2],
            fragment=f"L{line}",
        )

    def _resolve_path(
        self, document_uri: str, path_part: str, by_path: dict[str, str]
    ) -> str | None:
        base = Path(parse_local_uri(document_uri)[2]).parent
        candidate = _normalize(base / path_part.replace("\\", "/"))
        if candidate is None:
            return None
        names = [candidate]
        if not candidate.lower().endswith(".md"):
            names = [f"{candidate}.md", f"{candidate}/index.md"]
        for name in names:
            uri = by_path.get(name.casefold())
            if uri is not None:
                return uri
        return None

    def search(
        self, query: str, *, limit: int, cursor: str | None = None
    ) -> tuple[list[IndexedHit], str | None]:
        tokens = _tokens(query)
        if not self.exists() or not tokens:
            return [], None
        connection = self._connect()
        try:
            clauses = " OR ".join("lower(title) LIKE ? OR lower(body) LIKE ?" for _ in tokens)
            parameters = [value for token in tokens for value in (f"%{token}%", f"%{token}%")]
            rows = connection.execute(
                "SELECT uri, relative_path, title, content_hash, modified_at, body "
                f"FROM documents WHERE {clauses}",
                parameters,
            ).fetchall()
        finally:
            connection.close()
        scored: list[IndexedHit] = []
        for row in rows:
            title = str(row["title"])
            body = str(row["body"])
            score = _score(tokens, title, body)
            if score <= 0.0:
                continue
            scored.append(
                IndexedHit(
                    uri=str(row["uri"]),
                    relative_path=str(row["relative_path"]),
                    title=title,
                    content_hash=str(row["content_hash"]),
                    modified_at=datetime.fromisoformat(str(row["modified_at"])),
                    score=score,
                    snippet=_snippet(body, tokens),
                )
            )
        scored.sort(key=lambda hit: (-hit.score, hit.uri))
        offset = _cursor_offset(cursor)
        page = scored[offset : offset + limit]
        next_cursor = f"o:{offset + limit}" if offset + limit < len(scored) else None
        return page, next_cursor

    def document(self, relative_path: str) -> IndexedDocument | None:
        if not self.exists():
            return None
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT uri, relative_path, title, content_hash, size_bytes, modified_at "
                "FROM documents WHERE relative_path = ?",
                (relative_path,),
            ).fetchone()
            if row is None:
                return None
            uri = str(row["uri"])
            outgoing = tuple(
                (str(link["resolved_kind"]), str(link["resolved_node_id"]))
                for link in connection.execute(
                    "SELECT resolved_kind, resolved_node_id FROM links "
                    "WHERE document_uri = ? AND resolved_node_id IS NOT NULL "
                    "ORDER BY ordinal LIMIT 200",
                    (uri,),
                )
            )
            return IndexedDocument(
                uri=uri,
                relative_path=str(row["relative_path"]),
                title=str(row["title"]),
                content_hash=str(row["content_hash"]),
                size_bytes=int(row["size_bytes"]),
                modified_at=datetime.fromisoformat(str(row["modified_at"])),
                outgoing=outgoing,
            )
        finally:
            connection.close()

    def graph(self) -> GraphSnapshot:
        if not self.exists():
            return GraphSnapshot(nodes=(), edges=())
        connection = self._connect()
        try:
            return GraphSnapshot(
                nodes=_dedupe_nodes(self._graph_nodes(connection)),
                edges=_dedupe_edges(self._graph_edges(connection)),
            )
        finally:
            connection.close()

    def _graph_nodes(self, connection: sqlite3.Connection) -> list[GraphNodeRow]:
        nodes: list[GraphNodeRow] = []
        for row in connection.execute("SELECT uri, title FROM documents ORDER BY uri"):
            uri = str(row["uri"])
            nodes.append(
                GraphNodeRow(
                    node_id=doc_node_id(uri),
                    kind=NodeKind.DOCUMENT,
                    label=str(row["title"]),
                    uri=uri,
                    extractor="markdown_documents",
                    evidence_uri=uri,
                )
            )
        for row in connection.execute(
            "SELECT document_uri, line, text FROM headings ORDER BY document_uri, line"
        ):
            document_uri = str(row["document_uri"])
            line = int(row["line"])
            nodes.append(
                GraphNodeRow(
                    node_id=heading_node_id(document_uri, line),
                    kind=NodeKind.HEADING,
                    label=str(row["text"]),
                    uri=self._heading_uri(document_uri, line),
                    extractor="markdown_headings",
                    evidence_uri=document_uri,
                )
            )
        for row in connection.execute(
            "SELECT slug, tag, MIN(document_uri) AS document_uri FROM tags "
            "GROUP BY slug, tag ORDER BY slug"
        ):
            nodes.append(
                GraphNodeRow(
                    node_id=tag_node_id(str(row["slug"])),
                    kind=NodeKind.TAG,
                    label=str(row["tag"]),
                    uri=None,
                    extractor="markdown_tags",
                    evidence_uri=str(row["document_uri"]),
                )
            )
        return nodes

    def _graph_edges(self, connection: sqlite3.Connection) -> list[GraphEdgeRow]:
        edges: list[GraphEdgeRow] = []
        for row in connection.execute(
            "SELECT document_uri, line FROM headings ORDER BY document_uri, line"
        ):
            document_uri = str(row["document_uri"])
            line = int(row["line"])
            edges.append(
                GraphEdgeRow(
                    edge_id=_edge_id(
                        RelationKind.CONTAINS,
                        doc_node_id(document_uri),
                        heading_node_id(document_uri, line),
                    ),
                    kind=RelationKind.CONTAINS,
                    source_node_id=doc_node_id(document_uri),
                    target_node_id=heading_node_id(document_uri, line),
                    extractor="markdown_headings",
                    evidence_uri=document_uri,
                )
            )
        for row in connection.execute(
            "SELECT document_uri, kind, embed, resolved_node_id, resolved_uri "
            "FROM links WHERE resolved_node_id IS NOT NULL ORDER BY document_uri, ordinal"
        ):
            document_uri = str(row["document_uri"])
            embed = int(row["embed"]) == 1
            relation = RelationKind.EMBEDS if embed else RelationKind.LINKS_TO
            if embed:
                extractor = "markdown_embeds"
            elif str(row["kind"]) == LinkKind.WIKILINK.value:
                extractor = "markdown_wikilinks"
            else:
                extractor = "markdown_links"
            edges.append(
                GraphEdgeRow(
                    edge_id=_edge_id(
                        relation, doc_node_id(document_uri), str(row["resolved_node_id"])
                    ),
                    kind=relation,
                    source_node_id=doc_node_id(document_uri),
                    target_node_id=str(row["resolved_node_id"]),
                    extractor=extractor,
                    evidence_uri=str(row["resolved_uri"] or document_uri),
                )
            )
        for row in connection.execute(
            "SELECT document_uri, slug FROM tags ORDER BY document_uri, ordinal"
        ):
            document_uri = str(row["document_uri"])
            edges.append(
                GraphEdgeRow(
                    edge_id=_edge_id(
                        RelationKind.TAGGED_WITH,
                        doc_node_id(document_uri),
                        tag_node_id(str(row["slug"])),
                    ),
                    kind=RelationKind.TAGGED_WITH,
                    source_node_id=doc_node_id(document_uri),
                    target_node_id=tag_node_id(str(row["slug"])),
                    extractor="markdown_tags",
                    evidence_uri=document_uri,
                )
            )
        return edges


def doc_node_id(uri: str) -> str:
    return f"{DOC_NODE_PREFIX}:{_digest(uri)}"


def heading_node_id(uri: str, line: int) -> str:
    return f"{HEADING_NODE_PREFIX}:{_digest(f'{uri}#L{line}')}"


def tag_node_id(slug: str) -> str:
    return f"{TAG_NODE_PREFIX}:{slug or 'untitled'}"


def tag_slug(tag: str) -> str:
    cleaned = "-".join(part for part in tag.strip().lower().replace("/", "-").split("-") if part)
    return cleaned or "untitled"


def _edge_id(kind: RelationKind, source_node_id: str, target_node_id: str) -> str:
    return f"{EDGE_PREFIX}:{_digest(f'{kind.value}|{source_node_id}|{target_node_id}')}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _dedupe_nodes(nodes: Sequence[GraphNodeRow]) -> tuple[GraphNodeRow, ...]:
    seen: dict[str, GraphNodeRow] = {}
    for node in nodes:
        seen.setdefault(node.node_id, node)
    return tuple(seen[node_id] for node_id in sorted(seen))


def _dedupe_edges(edges: Sequence[GraphEdgeRow]) -> tuple[GraphEdgeRow, ...]:
    seen: dict[str, GraphEdgeRow] = {}
    for edge in edges:
        seen.setdefault(edge.edge_id, edge)
    return tuple(seen[edge_id] for edge_id in sorted(seen))


def _tokens(query: str) -> list[str]:
    raw = [token for token in query.lower().replace("/", " ").split() if len(token) >= 2]
    return raw[:8]


def _score(tokens: Sequence[str], title: str, body: str) -> float:
    if not tokens:
        return 0.0
    lowered_title = title.lower()
    lowered_body = body.lower()
    total = 0
    matched = 0
    for token in tokens:
        total += 2
        if token in lowered_title:
            matched += 2
        elif token in lowered_body:
            matched += 1
    return round(min(matched / total, 1.0), 4)


def _snippet(body: str, tokens: Sequence[str]) -> str:
    flat = " ".join(body.split())
    if not flat:
        return ""
    index = -1
    for token in tokens:
        index = flat.lower().find(token)
        if index >= 0:
            break
    start = max(0, index - 80) if index >= 0 else 0
    window = flat[start : start + MAX_SNIPPET_CHARS]
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + MAX_SNIPPET_CHARS < len(flat) else ""
    return f"{prefix}{window}{suffix}"


def _cursor_offset(cursor: str | None) -> int:
    if not cursor or not cursor.startswith("o:"):
        return 0
    try:
        return max(0, int(cursor[2:]))
    except ValueError:
        return 0


def _looks_external(path_part: str) -> bool:
    return bool(path_part) and (
        path_part.startswith(("/", "\\"))
        or path_part[:2].endswith(":")
        or "://" in path_part
        or path_part.startswith("#")
    )


def _normalize(path: Path) -> str | None:
    parts: list[str] = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts) if parts else None


def _line_fragment(fragment: str) -> int | None:
    if not fragment.startswith("L"):
        return None
    digits = fragment[1:].split("-", 1)[0]
    return int(digits) if digits.isdigit() else None
