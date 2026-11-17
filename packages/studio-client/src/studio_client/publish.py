from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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

PublishKind = Literal["rule", "skill", "agent", "hook", "model_profile", "workflow"]
PublishAction = Literal["created", "new_version", "unchanged"]

_LIBRARY_KIND: dict[str, LibraryKind] = {
    "rule": LibraryKind.RULE,
    "skill": LibraryKind.SKILL,
    "agent": LibraryKind.AGENT_DEFINITION,
    "hook": LibraryKind.HOOK,
    "model_profile": LibraryKind.MODEL_PROFILE,
    "workflow": LibraryKind.WORKFLOW,
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
    description: str | None = None


@dataclass(frozen=True)
class PublishResult:
    kind: PublishKind
    stable_key: str
    action: PublishAction
    version: int
    activated: bool


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
                description=item.description,
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
        LibraryVersionCreate(
            title=item.title,
            description=item.description,
            content=item.content,
            dependencies=pins,
        ),
        idempotency_key=str(uuid4()),
    )
    return await _maybe_activate(client, item, resource, created.version, "new_version", activate)


def _is_same(latest: LibraryVersion, item: PublishItem, pins: list[DependencyPin]) -> bool:
    return (
        latest.title == item.title
        and (item.description is None or latest.description == item.description)
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
