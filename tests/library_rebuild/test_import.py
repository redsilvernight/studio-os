from __future__ import annotations

import library_import as li
import pytest
from studio_client.errors import ForbiddenError, NotFoundError, StudioApiError
from studio_contracts.library import (
    LibraryKind,
    LibraryResource,
    LibraryResourceCreate,
    LibraryScope,
)

from .conftest import EXPECTED, Actor, World
from .conftest import actor_for as _actor_for

pytestmark = pytest.mark.asyncio(loop_scope="session")

KIND = {
    "rule": LibraryKind.RULE,
    "skill": LibraryKind.SKILL,
    "agent": LibraryKind.AGENT_DEFINITION,
    "hook": LibraryKind.HOOK,
    "model_profile": LibraryKind.MODEL_PROFILE,
    "workflow": LibraryKind.WORKFLOW,
}


async def _visible(actor: Actor, scope: LibraryScope, project_id=None) -> list[LibraryResource]:
    rows: list[LibraryResource] = []
    offset = 0
    while True:
        page = await actor.client.list_library_resources(
            scope=scope.value, project_id=project_id, limit=100, offset=offset
        )
        rows += page
        if len(page) < 100:
            return rows
        offset += 100


async def test_rebuild_counts(rebuilt: dict[str, dict[str, int]]) -> None:
    for layer, count in EXPECTED.items():
        assert rebuilt[layer]["created"] == count, (layer, rebuilt[layer])
        assert rebuilt[layer]["activated"] == count


@pytest.mark.parametrize("layer", ["core", "project", "personal"])
async def test_catalogue_matches_manifest(world: World, rebuilt: object, layer: str) -> None:
    plan = li.load_plan(layer)
    scope = li.SCOPE[layer]
    project_id = world.project_id if layer == "project" else None
    actor = _actor_for(world, layer)
    rows = await _visible(actor, scope, project_id)
    by_key = {(r.kind, r.stable_key): r for r in rows if r.scope == scope}
    assert len(by_key) == EXPECTED[layer]
    for item in plan.items:
        row = by_key[(KIND[item.kind], item.stable_key)]
        assert row.active_version == 1
        assert row.project_id == project_id
        if layer == "personal":
            assert row.owner_user_id == world.owner.user_id
        version = (await actor.client.list_library_versions(row.id))[0]
        assert version.title == item.title
        assert version.content == item.content
        assert len(version.dependencies) == len(item.pins)


async def test_second_run_is_noop(world: World, rebuilt: object) -> None:
    before = {
        layer: len(
            await _visible(
                _actor_for(world, layer),
                li.SCOPE[layer],
                world.project_id if layer == "project" else None,
            )
        )
        for layer in EXPECTED
    }
    for layer in EXPECTED:
        results = await li.import_plan(
            _actor_for(world, layer).client,
            li.load_plan(layer),
            project_id=world.project_id if layer == "project" else None,
        )
        summary = li.summarize(results)
        assert summary == {"unchanged": EXPECTED[layer], "activated": 0}
    for layer in EXPECTED:
        after = len(
            await _visible(
                _actor_for(world, layer),
                li.SCOPE[layer],
                world.project_id if layer == "project" else None,
            )
        )
        assert after == before[layer]


async def test_project_items_not_globally_visible(world: World, rebuilt: object) -> None:
    assert not [
        r
        for r in await _visible(world.admin, LibraryScope.STUDIO)
        if r.scope is not LibraryScope.STUDIO
    ]
    studio = await _visible(world.installer, LibraryScope.STUDIO)
    assert len(studio) == EXPECTED["core"]
    assert await _visible(world.outsider, LibraryScope.PROJECT, world.outsider_project_id) == []
    with pytest.raises(ForbiddenError):
        await _visible(world.outsider, LibraryScope.PROJECT, world.project_id)


async def test_outsider_cannot_reach_personal(world: World, rebuilt: object) -> None:
    mine = await _visible(world.owner, LibraryScope.USER)
    assert len(mine) == EXPECTED["personal"]
    assert await _visible(world.outsider, LibraryScope.USER) == []
    visible_ids = {r.id for r in await world.outsider.client.list_library_resources(limit=100)}
    assert visible_ids.isdisjoint({r.id for r in mine})
    for row in mine:
        for call in (
            world.outsider.client.get_library_resource,
            world.outsider.client.list_library_versions,
        ):
            with pytest.raises((NotFoundError, ForbiddenError)):
                await call(row.id)
    private_keys = {r.stable_key for r in mine} - {
        r.stable_key for r in await _visible(world.outsider, LibraryScope.STUDIO)
    }
    assert private_keys
    for key in private_keys:
        with pytest.raises(StudioApiError):
            await world.outsider.client.resolve_agent(key, project_id=world.outsider_project_id)


async def test_readonly_cannot_publish(world: World, rebuilt: object) -> None:
    synthetic = LibraryResourceCreate(
        kind=LibraryKind.RULE,
        stable_key="synthetic-forbidden",
        scope=LibraryScope.STUDIO,
        title="x",
        content={"content_schema": "studio.library.rule/v1", "text": "x"},
    )
    with pytest.raises(ForbiddenError):
        await world.readonly.client.create_library_resource(
            synthetic, idempotency_key="synthetic-forbidden-1"
        )


def test_personal_hooks_excluded_from_all_packages() -> None:
    for layer in ("project", "personal"):
        assert not [i for i in li.load_plan(layer).items if i.kind == "hook"]
    assert {i.stable_key for i in li.load_plan("core").items if i.kind == "hook"} == {
        "git-guard",
        "session-start",
        "stop-check",
    }
