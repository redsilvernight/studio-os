from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from uuid import UUID, uuid4

from studio_contracts.library import (
    SKILL_FILE_TEXT_MAX_LENGTH,
    SKILL_FILES_MAX,
    SKILL_FILES_TOTAL_MAX_LENGTH,
    DependencyPin,
    LibraryActivate,
    LibraryKind,
    LibraryResource,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersion,
    LibraryVersionCreate,
    skill_file_path_error,
)

from studio_client.api_client import StudioApiClient
from studio_client.canonical import (
    _split_frontmatter,
    canonical_agent_keys,
    canonical_rule_keys,
    canonical_skill_keys,
    load_definition,
    load_rule_meta,
    load_skill_files,
    load_skill_text,
    model_profile_key,
    to_model_profile_payload,
    to_publish_payload,
)

PublishKind = Literal["rule", "skill", "agent", "hook", "model_profile", "workflow"]
PUBLISH_KINDS: tuple[PublishKind, ...] = ("rule", "skill", "agent")
# `hook`, `model_profile` and `workflow` are publishable (package import) but
# `build_publish_items` only lists `rule`/`skill`/`agent`: a `model_profile` is
# built implicitly from its agent's `requirements` and published right before
# that agent, so `--kind agent` keeps working (the CLI `--kind` choices stay
# `rule|skill|agent`).
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


def _skill_files(repo_root: Path, key: str) -> list[dict[str, str]]:
    """`skill/v1` auxiliary files, within the contract budgets. Anything the
    server would reject stops here with an explicit `PublishError` instead of
    a late 422 after a partial publication."""
    files = load_skill_files(repo_root, key)
    if len(files) > SKILL_FILES_MAX:
        raise PublishError(f"skill {key!r}: {len(files)} auxiliary files, max {SKILL_FILES_MAX}")
    for file in files:
        error = skill_file_path_error(file["path"])
        if error:
            raise PublishError(f"skill {key!r}: {file['path']!r}: {error}")
        if len(file["text"]) > SKILL_FILE_TEXT_MAX_LENGTH:
            raise PublishError(
                f"skill {key!r}: {file['path']} exceeds {SKILL_FILE_TEXT_MAX_LENGTH} chars"
            )
    if sum(len(file["text"]) for file in files) > SKILL_FILES_TOTAL_MAX_LENGTH:
        raise PublishError(
            f"skill {key!r}: auxiliary files exceed {SKILL_FILES_TOTAL_MAX_LENGTH} chars in total"
        )
    return files


def _typed_pins(pins: Sequence[tuple[str, str]]) -> tuple[tuple[PublishKind, str], ...]:
    typed: list[tuple[PublishKind, str]] = []
    for kind, key in pins:
        if kind not in _LIBRARY_KIND:
            raise PublishError(f"unknown dependency kind {kind!r} for {key!r}")
        typed.append((cast(PublishKind, kind), key))
    return tuple(typed)


def build_publish_items(
    repo_root: Path | str,
    *,
    kinds: Sequence[PublishKind] = PUBLISH_KINDS,
    keys: Sequence[str] = (),
) -> list[PublishItem]:
    """Canonical `.agents/` resources as Library payloads, ordered rules →
    skills → model_profiles → agents so a dependency is always published
    before its pinner. A `model_profile` is built from its agent's
    `requirements` and selected with that agent (`--kind agent`), never listed
    on its own. `keys` narrows every selected kind; a key matching no selected
    kind is an error, never a silent no-op."""
    root = Path(repo_root)
    available: dict[str, list[str]] = {
        "rule": canonical_rule_keys(root),
        "skill": canonical_skill_keys(root),
        "agent": canonical_agent_keys(root),
    }
    selected = set(keys)
    unknown = selected - {key for kind_keys in available.values() for key in kind_keys}
    if unknown:
        raise PublishError(f"no canonical resource for: {', '.join(sorted(unknown))}")
    selected_kinds = set(kinds)
    if "model_profile" in selected_kinds and "agent" not in selected_kinds:
        raise PublishError("model_profile is published with its agent; select the 'agent' kind too")
    items: list[PublishItem] = []
    if "rule" in selected_kinds:
        for key in available["rule"]:
            if selected and key not in selected:
                continue
            applies_to, body = load_rule_meta(root, key)
            items.append(
                PublishItem(
                    "rule",
                    key,
                    key,
                    {
                        "content_schema": "studio.library.rule/v2",
                        "text": body,
                        "applies_to": applies_to,
                    },
                )
            )
    if "skill" in selected_kinds:
        for key in available["skill"]:
            if selected and key not in selected:
                continue
            content: dict[str, object] = {
                "content_schema": "studio.library.skill/v1",
                "text": load_skill_text(root, key),
            }
            files = _skill_files(root, key)
            if files:
                content["files"] = files
            items.append(PublishItem("skill", key, _skill_title(root, key), content))
    if "agent" in selected_kinds:
        profiles: list[PublishItem] = []
        agents: list[PublishItem] = []
        for key in available["agent"]:
            if selected and key not in selected:
                continue
            agent = load_definition(root, key)
            if agent.requirements:
                profiles.append(
                    PublishItem(
                        "model_profile",
                        model_profile_key(key),
                        agent.title,
                        to_model_profile_payload(agent),
                    )
                )
            content, pins = to_publish_payload(agent)
            agents.append(PublishItem("agent", key, agent.title, content, _typed_pins(pins)))
        items.extend(profiles)
        items.extend(agents)
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
