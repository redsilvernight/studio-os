from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from studio_contracts.library import RuleContent, SkillContent

from studio_client.context.errors import ContextError
from studio_client.context.manifest import SourceRef

LIBRARY_CONTEXT_KIND = "library"
"""Additive Context Package kind carrying AI Library excerpts (P9/DEC-0073).

DEC-0057 closes the 8.3b kind set but states a new kind is additive, never a
rename — `library` is that additive kind. It never collides with the closed
Library taxonomy (`rule`, `skill`, …), which travels inside each item as
`library_kind`.
"""

TEXTUAL_LIBRARY_KINDS: tuple[str, ...] = ("rule", "skill")
"""Only free-prose Library kinds are injectable as context text (P3/DEC-0066).

`model_profile` carries capability requirements (not prose to inject),
`agent_definition` is structural (P5 resolution owns it — P9 never resolves),
`workflow` is a declarative definition (P11/DEC-0075 — participants, DAG and
I/O, no injectable prose). Those kinds are skipped with `out_of_scope`, never
serialized blindly.
"""

_SCOPE_RANK = {"user": 0, "project": 1, "studio": 2}
"""Shadowing rank mirrored from the public DEC-0065 total order
(`User > Project(project_id) > Studio`). Applied client-side over the
already-visible rows returned by the P7 `GET /api/v1/library` listing (which
filters visibility first but does not resolve shadowing): pure deterministic
selection, no server rule reimplemented, no invisible candidate ever named.
"""


@dataclass(frozen=True)
class LibraryContextItem:
    """One effective Library definition normalized for the Context Package."""

    library_kind: str
    stable_key: str
    version: int
    version_origin: str
    scope: str
    title: str
    text: str
    content_schema: str
    deprecated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "library_kind": self.library_kind,
            "stable_key": self.stable_key,
            "version": self.version,
            "version_origin": self.version_origin,
            "scope": self.scope,
            "title": self.title,
            "text": self.text,
            "content_schema": self.content_schema,
            "deprecated": self.deprecated,
        }


@dataclass(frozen=True)
class LibraryFetchResult:
    """Normalized candidates plus skip counts per omission reason."""

    items: list[LibraryContextItem] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)


class LibraryContextProvider:
    """AI Library as one more source of the local composer (P9/DEC-0073).

    Reads through `StudioApiClient` over the P7 HTTP surface only — never MCP
    (`studio_discover_definitions` is for agents/harnesses), never a second
    HTTP client, never direct DB access. Returns normalized candidates; the
    composer alone applies priority, budget and `omitted[]`.

    `TransportError` (connection refused, timeout, DNS — anything without an
    HTTP response) propagates so the composer can degrade to
    `omitted(server_unreachable)`. Any other failure (auth, contract,
    invalid content) also propagates: degraded mode must never mask it.
    """

    def __init__(self, api_client: Any) -> None:
        self._api = api_client

    async def fetch(
        self,
        project_id: UUID | None,
        *,
        limit: int = 100,
        kinds: tuple[str, ...] = TEXTUAL_LIBRARY_KINDS,
    ) -> LibraryFetchResult:
        resources = await self._api.list_library_resources(limit=limit)
        wanted = set(kinds)
        locks = await self._api.list_library_locks(project_id=project_id)
        locked_version = {lock.resource_id: lock.locked_version for lock in locks}

        visible = [r for r in resources if self._is_applicable(r, project_id)]
        effective = self._apply_shadowing(visible)

        items: list[LibraryContextItem] = []
        skipped: dict[str, int] = {}
        for resource in sorted(effective, key=lambda r: (str(r.kind), r.stable_key)):
            kind = str(resource.kind)
            if kind not in wanted or kind not in TEXTUAL_LIBRARY_KINDS:
                skipped["out_of_scope"] = skipped.get("out_of_scope", 0) + 1
                continue
            version_number = locked_version.get(resource.id, resource.active_version)
            origin = "lock" if resource.id in locked_version else "active"
            if version_number <= 0:
                skipped["missing"] = skipped.get("missing", 0) + 1
                continue
            version_row = await self._find_version(resource.id, version_number)
            if version_row is None:
                skipped["missing"] = skipped.get("missing", 0) + 1
                continue
            items.append(self._to_item(resource, version_row, version_number, origin))
        return LibraryFetchResult(items=items, skipped=skipped)

    def _is_applicable(self, resource: Any, project_id: UUID | None) -> bool:
        """Keep rows from the layer stack valid for this composition.

        Studio and user rows always apply (visibility was enforced
        server-side, filter-first). Project rows apply only to their own
        project — without a `project_id` the Project layer is absent
        (DEC-0065 §1). Unknown scopes fail closed.
        """
        scope = str(resource.scope)
        if scope == "studio" or scope == "user":
            return True
        if scope == "project":
            return project_id is not None and resource.project_id == project_id
        return False

    @staticmethod
    def _apply_shadowing(resources: list[Any]) -> list[Any]:
        """One effective definition per `(kind, stable_key)`: lowest rank wins.

        Shadowed rows are dropped silently — per DEC-0065 §7 the provenance
        names the effective resource only, never the discarded candidates.
        Deterministic regardless of HTTP/DB return order.
        """
        best: dict[tuple[str, str], Any] = {}
        for resource in resources:
            key = (str(resource.kind), resource.stable_key)
            rank = _SCOPE_RANK.get(str(resource.scope), 99)
            current = best.get(key)
            if current is None or rank < _SCOPE_RANK.get(str(current.scope), 99):
                best[key] = resource
        return list(best.values())

    async def _find_version(self, resource_id: UUID, version_number: int) -> Any | None:
        versions = await self._api.list_library_versions(resource_id)
        for row in versions:
            if row.version == version_number:
                return row
        return None

    @staticmethod
    def _to_item(
        resource: Any, version_row: Any, version_number: int, origin: str
    ) -> LibraryContextItem:
        kind = str(resource.kind)
        content = dict(version_row.content)
        try:
            if kind == "rule":
                parsed = RuleContent.model_validate(content)
            elif kind == "skill":
                parsed = SkillContent.model_validate(content)
            else:
                raise ContextError(
                    "unsupported_library_kind",
                    f"library kind {kind!r} has no context text mapping",
                )
        except ValidationError as exc:
            raise ContextError(
                "invalid_library_content",
                f"library {kind}/{resource.stable_key} v{version_number} "
                f"violates its P3 content schema",
            ) from exc
        status = str(getattr(resource, "status", "active"))
        return LibraryContextItem(
            library_kind=kind,
            stable_key=resource.stable_key,
            version=version_number,
            version_origin=origin,
            scope=str(resource.scope),
            title=version_row.title,
            text=parsed.text,
            content_schema=str(parsed.content_schema),
            deprecated=status == "deprecated",
        )


def library_source_ref(project_id: UUID | None, included: int) -> SourceRef:
    """Safe provenance for the library source: logical identifiers only
    (`kind`, project UUID, count) — never a local path, never content."""
    return SourceRef(
        kind=LIBRARY_CONTEXT_KIND,
        ref=f"library:{project_id}" if project_id is not None else "library:global",
        included=included,
    )
