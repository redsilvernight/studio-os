from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from studio_contracts.library import (
    DependencyPin,
    LibraryActivate,
    LibraryKind,
    LibraryResource,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersion,
    LibraryVersionCreate,
)

from studio_client.api_client import StudioApiClient
from studio_client.canonical import (
    _split_frontmatter,
    canonical_agent_keys,
    canonical_rule_keys,
    canonical_skill_keys,
    load_definition,
    load_rule_text,
    load_skill_text,
    to_publish_payload,
)

PublishKind = Literal["rule", "skill", "agent"]
PUBLISH_KINDS: tuple[PublishKind, ...] = ("rule", "skill", "agent")
PublishAction = Literal["created", "new_version", "unchanged"]

_LIBRARY_KIND: dict[str, LibraryKind] = {
    "rule": LibraryKind.RULE,
    "skill": LibraryKind.SKILL,
    "agent": LibraryKind.AGENT_DEFINITION,
}
_LISTING_PAGE = 500


class PublishError(Exception):
    """A publication that must stop before (or while) touching the Library."""


@dataclass(frozen=True)
class PublishItem:
    kind: PublishKind
    stable_key: str
    title: str
    content: dict[str, object]
    pins: tuple[tuple[PublishKind, str], ...] = ()


@dataclass(frozen=True)
class PublishResult:
    kind: PublishKind
    stable_key: str
    action: PublishAction
    version: int
    activated: bool


def _skill_title(repo_root: Path, key: str) -> str:
    path = repo_root / ".agents" / "skills" / key / "SKILL.md"
    data, _ = _split_frontmatter(path.read_text(encoding="utf-8"), source=str(path))
    return " ".join(str(data.get("description") or key).split())


def build_publish_items(
    repo_root: Path | str,
    *,
    kinds: Sequence[PublishKind] = PUBLISH_KINDS,
    keys: Sequence[str] = (),
) -> list[PublishItem]:
    """Canonical `.agents/` resources as Library payloads, ordered rules →
    skills → agents so a dependency is always published before its pinner.
    `keys` narrows every selected kind; a key matching no selected kind is an
    error, never a silent no-op."""
    root = Path(repo_root)
    available: dict[PublishKind, list[str]] = {
        "rule": canonical_rule_keys(root),
        "skill": canonical_skill_keys(root),
        "agent": canonical_agent_keys(root),
    }
    selected = set(keys)
    unknown = selected - {key for kind in kinds for key in available[kind]}
    if unknown:
        raise PublishError(f"no canonical resource for: {', '.join(sorted(unknown))}")
    items: list[PublishItem] = []
    for kind in PUBLISH_KINDS:
        if kind not in kinds:
            continue
        for key in available[kind]:
            if selected and key not in selected:
                continue
            if kind == "rule":
                content: dict[str, object] = {
                    "content_schema": "studio.library.rule/v1",
                    "text": load_rule_text(root, key),
                }
                items.append(PublishItem(kind, key, key, content))
            elif kind == "skill":
                content = {
                    "content_schema": "studio.library.skill/v1",
                    "text": load_skill_text(root, key),
                }
                items.append(PublishItem(kind, key, _skill_title(root, key), content))
            else:
                agent = load_definition(root, key)
                content, pins = to_publish_payload(agent)
                typed_pins: tuple[tuple[PublishKind, str], ...] = tuple(
                    ("rule" if pin_kind == "rule" else "skill", pin_key)
                    for pin_kind, pin_key in pins
                )
                items.append(PublishItem(kind, key, agent.title, content, typed_pins))
    return items


def _same_pins(existing: Sequence[DependencyPin], wanted: Sequence[DependencyPin]) -> bool:
    def norm(pins: Sequence[DependencyPin]) -> set[tuple[str, str, int]]:
        return {(p.kind.value, p.stable_key, p.version) for p in pins}

    return norm(existing) == norm(wanted)


async def _find_resource(
    client: StudioApiClient,
    kind: LibraryKind,
    key: str,
    scope: LibraryScope,
    project_id: UUID | None,
) -> LibraryResource | None:
    offset = 0
    while True:
        page = await client.list_library_resources(
            kind=kind.value,
            scope=scope.value,
            project_id=project_id,
            limit=_LISTING_PAGE,
            offset=offset,
        )
        for resource in page:
            if resource.stable_key == key and resource.project_id == project_id:
                return resource
        if len(page) < _LISTING_PAGE:
            return None
        offset += _LISTING_PAGE


async def _external_pin_version(
    client: StudioApiClient,
    kind: LibraryKind,
    key: str,
    scope: LibraryScope,
    project_id: UUID | None,
) -> int | None:
    """Active version of a dependency this run does not publish: the
    publication scope first, then Studio. Drafts are never pinned implicitly."""
    lookups: list[tuple[LibraryScope, UUID | None]] = [(scope, project_id)]
    if scope is not LibraryScope.STUDIO:
        lookups.append((LibraryScope.STUDIO, None))
    for lookup_scope, lookup_project in lookups:
        found = await _find_resource(client, kind, key, lookup_scope, lookup_project)
        if found is not None and found.active_version > 0:
            return found.active_version
    return None


async def publish_items(
    client: StudioApiClient,
    items: Sequence[PublishItem],
    *,
    scope: LibraryScope,
    project_id: UUID | None,
    activate: bool = False,
    dry_run: bool = False,
) -> list[PublishResult]:
    """Publish canonical items to the Library (Studio or Project scope).

    Idempotent: an item identical to the resource's latest version (content,
    title, pinned dependencies) is `unchanged`; otherwise version N+1 is
    added. Nothing activates unless `activate` is set — the server never
    self-activates either. A dependency pin resolves to the version this run
    just published/kept, else to the dependency's active version; if neither
    exists the run stops (fail closed). `dry_run` only reads."""
    if (scope is LibraryScope.PROJECT) != (project_id is not None):
        raise PublishError("--project-id is required for, and only valid with, project scope")
    if scope is LibraryScope.USER:
        raise PublishError("user scope is not a publication target")

    published: dict[tuple[PublishKind, str], int] = {}
    results: list[PublishResult] = []
    for item in items:
        pins: list[DependencyPin] = []
        for pin_kind, pin_key in item.pins:
            version = published.get((pin_kind, pin_key))
            if version is None:
                version = await _external_pin_version(
                    client, _LIBRARY_KIND[pin_kind], pin_key, scope, project_id
                )
            if version is None:
                raise PublishError(
                    f"{item.kind} {item.stable_key!r} pins {pin_kind} {pin_key!r}, "
                    "which has no published version to pin"
                )
            pins.append(
                DependencyPin(kind=_LIBRARY_KIND[pin_kind], stable_key=pin_key, version=version)
            )
        results.append(
            await _publish_one(
                client,
                item,
                pins,
                scope=scope,
                project_id=project_id,
                activate=activate,
                dry_run=dry_run,
            )
        )
        published[(item.kind, item.stable_key)] = results[-1].version
    return results


async def _publish_one(
    client: StudioApiClient,
    item: PublishItem,
    pins: list[DependencyPin],
    *,
    scope: LibraryScope,
    project_id: UUID | None,
    activate: bool,
    dry_run: bool,
) -> PublishResult:
    kind = _LIBRARY_KIND[item.kind]
    resource = await _find_resource(client, kind, item.stable_key, scope, project_id)
    if resource is None:
        if dry_run:
            return PublishResult(item.kind, item.stable_key, "created", 1, False)
        resource = await client.create_library_resource(
            LibraryResourceCreate(
                kind=kind,
                stable_key=item.stable_key,
                scope=scope,
                project_id=project_id,
                title=item.title,
                content=item.content,
                dependencies=pins,
            ),
            idempotency_key=str(uuid4()),
        )
        return await _maybe_activate(client, item, resource, 1, "created", activate)

    versions = await client.list_library_versions(resource.id)
    latest = max(versions, key=lambda v: v.version, default=None)
    if latest is not None and _is_same(latest, item, pins):
        if dry_run:
            return PublishResult(
                item.kind,
                item.stable_key,
                "unchanged",
                latest.version,
                activate and resource.active_version != latest.version,
            )
        return await _maybe_activate(client, item, resource, latest.version, "unchanged", activate)
    next_version = (latest.version if latest is not None else 0) + 1
    if dry_run:
        return PublishResult(item.kind, item.stable_key, "new_version", next_version, False)
    created = await client.create_library_version(
        resource.id,
        LibraryVersionCreate(title=item.title, content=item.content, dependencies=pins),
        idempotency_key=str(uuid4()),
    )
    return await _maybe_activate(client, item, resource, created.version, "new_version", activate)


def _is_same(latest: LibraryVersion, item: PublishItem, pins: list[DependencyPin]) -> bool:
    return (
        latest.title == item.title
        and latest.content == item.content
        and _same_pins(latest.dependencies, pins)
    )


async def _maybe_activate(
    client: StudioApiClient,
    item: PublishItem,
    resource: LibraryResource,
    version: int,
    action: PublishAction,
    activate: bool,
) -> PublishResult:
    activated = False
    if activate:
        current = await client.get_library_resource(resource.id)
        if current.active_version == version:
            return PublishResult(item.kind, item.stable_key, action, version, False)
        await client.activate_library_version(
            resource.id,
            LibraryActivate(version=version, expected_resource_version=current.version),
            idempotency_key=str(uuid4()),
        )
        activated = True
    return PublishResult(item.kind, item.stable_key, action, version, activated)
