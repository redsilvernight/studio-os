"""P12-project: server `resolve_definition` and the client
`LibraryContextProvider` pick the same effective definition on crossed cases
(user > project > studio, locks per DEC-0065 §6)."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import library as library_service
from studio_api.services import projects as projects_service
from studio_client.context.library import LibraryContextProvider
from studio_client.errors import StudioApiError
from studio_contracts.library import (
    LibraryKind,
    LibraryLockCreate,
    LibraryScope,
    LibraryVersionCreate,
)

from tests.api.test_library_resolution import _activate, _create, _principal


class _DbApi:
    """The slice of `StudioApiClient` the provider reads, served by the service layer."""

    def __init__(self, session: AsyncSession, principal) -> None:
        self.session, self.principal = session, principal

    async def list_library_resources(self, *, limit: int = 100, offset: int = 0, **_: object):
        return await library_service.list_resources(
            self.session, self.principal, limit=limit, offset=offset
        )

    async def list_library_locks(self, *, project_id: UUID | None):
        return await library_service.list_locks(self.session, self.principal, project_id)

    async def list_library_versions(self, resource_id: UUID):
        return await library_service.list_versions(self.session, resource_id)

    async def batch_library_versions(self, refs):
        raise StudioApiError(404, None, "no batch route")


async def _bump(session: AsyncSession, principal, resource) -> None:
    """Add and activate v2, so a lock on v1 differs from the active version."""
    await session.refresh(resource)
    await library_service.create_resource_version(
        session,
        principal,
        resource,
        LibraryVersionCreate(
            title="v2", content={"content_schema": "studio.library.rule/v1", "text": "v2"}
        ),
    )
    await _activate(session, principal, resource, 2)


async def test_client_and_server_agree_on_crossed_cases(
    db_session: AsyncSession, machine: tuple[MachineModel, str], project: ProjectModel
) -> None:
    principal = await _principal(db_session, machine)
    other = await projects_service.create_project(
        db_session, "p12-other", "Other Project", None, creator=None
    )
    s, p, u = LibraryScope.STUDIO, LibraryScope.PROJECT, LibraryScope.USER
    layers = {
        "studio-only": [(s, None)],
        "studio-project": [(s, None), (p, project.id)],
        "all-three": [(s, None), (p, project.id), (u, None)],
        "user-studio": [(s, None), (u, None)],
        "project-only": [(p, project.id)],
        "other-project": [(s, None), (p, other.id)],
        "locked-project": [(p, project.id)],
        "locked-studio": [(s, None)],
        "locked-shadowed": [(p, project.id), (u, None)],
    }
    made: dict[str, list] = {}
    for key, stack in layers.items():
        made[key] = []
        for scope, pid in stack:
            resource = await _create(db_session, principal, key, scope, pid)
            await _activate(db_session, principal, resource)
            made[key].append(resource)
    for key in ("locked-project", "locked-studio", "locked-shadowed"):
        resource = made[key][0]
        await _bump(db_session, principal, resource)
        await library_service.set_lock(
            db_session,
            principal,
            LibraryLockCreate(project_id=project.id, resource_id=resource.id, locked_version=1),
        )

    provider = LibraryContextProvider(_DbApi(db_session, principal))
    seen: set[tuple[str, UUID | None]] = set()
    for project_id in (project.id, other.id, None):
        client = {
            i.stable_key: (i.scope, i.version, i.version_origin)
            for i in (await provider.fetch(project_id)).items
        }
        for key in layers:
            try:
                r = await library_service.resolve_definition(
                    db_session, principal, LibraryKind.RULE, key, project_id
                )
                server = (r.scope.value, r.version, r.version_origin.value)
            except HTTPException:
                server = None
            assert client.get(key) == server, (key, project_id)
            seen.add((key, project_id))
    assert len(seen) == len(layers) * 3
