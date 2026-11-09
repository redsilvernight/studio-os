"""P12-project: the Library sync honours project locks and the Project layer
(DEC-0065 §1, §6). Server parity: tests/api/test_library_resolution_parity.py."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from studio_client.context.library import LibraryContextProvider
from studio_client.daemon import skills_bridge

from tests.client.test_daemon_library_sync import _ReadOnlyApi, _Resource, _Version

P1, P2 = uuid4(), uuid4()


class _Lock:
    def __init__(self, resource_id: UUID, locked_version: int) -> None:
        self.resource_id = resource_id
        self.locked_version = locked_version


class _LockApi(_ReadOnlyApi):
    """Locks belong to P1 only, like the server's per-project lock listing."""

    def __init__(self, resources, versions, locks) -> None:
        super().__init__(resources, versions)
        self.locks = locks

    async def list_library_locks(self, *, project_id):
        return self.locks if project_id == P1 else []


def _version(resource: _Resource, version: int) -> _Version:
    return _Version(
        resource.id,
        version,
        f"{resource.stable_key} v{version}",
        {"content_schema": "studio.library.rule/v1", "text": f"{resource.stable_key} v{version}"},
    )


def test_project_lock_is_respected_by_the_sync() -> None:
    pinned = _Resource(uuid4(), "pinned", "rule", active_version=2)
    floating = _Resource(uuid4(), "floating", "rule", active_version=2)
    versions = [_version(r, v) for r in (pinned, floating) for v in (1, 2)]
    api = _LockApi([pinned, floating], versions, [_Lock(pinned.id, 1)])

    locked = asyncio.run(skills_bridge.fetch_library_projections(api, P1))
    assert {i.stable_key: (i.version, i.version_origin) for i in locked} == {
        "pinned": (1, "lock"),
        "floating": (2, "active"),
    }
    # The lock belongs to its project: another project, or none, follows active.
    for project_id in (P2, None):
        other = asyncio.run(skills_bridge.fetch_library_projections(api, project_id))
        assert {(i.stable_key, i.version, i.version_origin) for i in other} == {
            ("pinned", 2, "active"),
            ("floating", 2, "active"),
        }


def test_project_resource_only_appears_for_its_project() -> None:
    mine = _Resource(uuid4(), "mine", "rule", scope="project", project_id=P1)
    theirs = _Resource(uuid4(), "theirs", "rule", scope="project", project_id=P2)
    api = _ReadOnlyApi([mine, theirs], [_version(mine, 1), _version(theirs, 1)])
    provider = LibraryContextProvider(api)

    def keys(project_id: UUID | None) -> set[str]:
        return {i.stable_key for i in asyncio.run(provider.fetch(project_id)).items}

    assert keys(P1) == {"mine"}
    assert keys(P2) == {"theirs"}
    assert keys(None) == set()
    # Project definitions are never projected into the shared home.
    assert asyncio.run(skills_bridge.fetch_library_projections(api, P1)) == ()
