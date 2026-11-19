from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import Field
from studio_contracts.auth import Role
from studio_contracts.claims import ResourceClaim
from studio_contracts.project_state import ProjectState
from studio_contracts.projects import (
    Project,
    ProjectCreate,
    ProjectMember,
    ProjectRead,
    ProjectRepository,
    ProjectRepositoryCreate,
    ResolveRepositoryRequest,
    ResolveRepositoryResponse,
)
from studio_contracts.tasks import Task

from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.user import UserModel
from studio_api.deps import CurrentPrincipal, DbSession, require_roles
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import project_repositories as project_repositories_service
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import with_created_project

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectCreateRequest(ProjectCreate):
    """`POST /projects` payload: the canonical `ProjectCreate` fields plus an
    optional `repository` (any URL form, normalized server-side like
    `ProjectRepositoryCreate.url`, 512 characters max), registered with the
    project in the same call so `resolve-repository` finds it immediately.

    Router-local on purpose: the frozen `studio_contracts` shape is reused
    unchanged, so this is an additive *input* field of this route only — a
    client sending the canonical fields alone behaves exactly as before.
    Absent, the project is created alone and its remotes are linked later."""

    repository: str | None = Field(default=None, max_length=512)


@router.get(
    "",
    response_model=list[ProjectRead],
    description=(
        "List the projects the caller may access: every project for an "
        "admin, the projects the caller's User is a member of otherwise. "
        "Each entry carries its linked repository URLs (`repositories`)."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_projects(session: DbSession, principal: CurrentPrincipal) -> list[ProjectRead]:
    projects = await projects_service.list_projects(session, principal)
    return await project_repositories_service.projects_read(session, projects)


@router.post(
    "",
    response_model=Project,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create a project. Requires a privileged role (admin or "
        "developer); other roles receive `403 forbidden`. Slugs are "
        "unique: reusing one fails with 409. The creator becomes a member "
        "of the new project. The optional `repository` is registered with "
        "the project in the same call (`resolve-repository` finds it "
        "immediately); a URL already linked to another project fails with "
        "`409 repository_already_linked` and an invalid one with `422 "
        "invalid_repository_url`, both before the project is written. "
        "Accepts `Idempotency-Key` for safe retries."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        status.HTTP_409_CONFLICT: {
            "description": (
                "Nothing created: the slug is already used (`conflict`), "
                "`repository` is already linked to another project "
                "(`repository_already_linked`), or the replay key is wrong "
                "(`idempotency_key_payload_mismatch` / "
                "`idempotency_key_in_progress`)."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "repository_already_linked": {
                            "value": {
                                "detail": {
                                    "error_code": "repository_already_linked",
                                    "message": ("repository is already linked to another project"),
                                    "url": "github.com/org/repo",
                                }
                            }
                        },
                        "idempotency_key_payload_mismatch": {
                            "value": {"detail": {"error_code": "idempotency_key_payload_mismatch"}}
                        },
                    }
                }
            },
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Nothing stored: `repository` was refused "
                "(`invalid_repository_url`) or the body itself is invalid "
                "(framework `HTTPValidationError`, e.g. an over-long URL)."
            ),
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/HTTPValidationError"},
                    "example": {
                        "detail": {
                            "error_code": "invalid_repository_url",
                            "message": "invalid repository url: 'not-a-url'",
                        }
                    },
                }
            },
        },
    },
)
async def create_project(
    project_in: ProjectCreateRequest,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    _owner: Annotated[UserModel, Depends(require_roles(Role.ADMIN, Role.DEVELOPER))],
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> Project:
    async def _create() -> Project:
        # The remote is validated before the project is written, so a refused
        # URL leaves nothing behind (same codes as the standalone link route).
        # The link itself goes through `link_repository`, which normalizes the
        # raw URL; `ensure_remote_available` only checks it first.
        if project_in.repository is not None:
            await project_repositories_service.ensure_remote_available(
                session, project_in.repository
            )
        project = await projects_service.create_project(
            session,
            project_in.slug,
            project_in.name,
            project_in.description,
            creator=principal.user,
            studio_id=principal.studio_id,
        )
        if project_in.repository is not None:
            await project_repositories_service.link_repository(
                session,
                with_created_project(principal, project.id),
                project.id,
                project_in.repository,
            )
        return await project_repositories_service.project_read(session, project)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /projects",
        Project,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectRead,
    description=(
        "Get one project by id, with its linked repository URLs "
        "(`repositories`). A project the caller may not access — "
        "nonexistent included — answers `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_project(
    project_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> ProjectRead:
    project = await projects_service.get_project(session, principal, project_id)
    return await project_repositories_service.project_read(session, project)


@router.get(
    "/{project_id}/state",
    response_model=ProjectState,
    description=(
        "Bootstrap read for a project: its active tasks and active "
        "resource claims in one call. Start here before working on a "
        "project. Same project access rule as `GET /projects/{id}`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_project_state(
    project_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> ProjectState:
    await projects_service.get_project(session, principal, project_id)
    tasks = await projects_service.get_active_tasks(session, principal, project_id)
    claims = await projects_service.get_active_claims(session, principal, project_id)

    return ProjectState(
        project_id=project_id,
        active_tasks=[Task.model_validate(t) for t in tasks],
        active_claims=[ResourceClaim.model_validate(c) for c in claims],
        generated_at=datetime.now(UTC),
    )


def _member_out(membership: ProjectMembershipModel, user: UserModel | None) -> ProjectMember:
    member = ProjectMember.model_validate(membership)
    if user is None:
        return member
    return member.model_copy(
        update={"user_display_name": user.display_name, "user_email": user.email}
    )


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMember],
    description=(
        "List the users with access to a project. Requires the "
        "admin role: any other role gets `403 forbidden` before any lookup. "
        "Unknown project: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def list_project_members(
    project_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> list[ProjectMember]:
    projects_service.ensure_members_admin(principal, "read")
    members = await projects_service.list_members(
        session, project_id, studio_id=principal.studio_id
    )
    users = await provisioning_service.users_by_id(session, {m.user_id for m in members})
    return [_member_out(m, users.get(m.user_id)) for m in members]


@router.put(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMember,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Grant a user access to a project (admin only). `201` with the new "
        "membership; granting an existing member returns it unchanged with "
        "`200` (the original `granted_by_user_id` is kept). Naturally "
        "idempotent: no `Idempotency-Key`. Granting yourself: `403 "
        "self_modification_forbidden`. Unknown project or user: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def grant_project_member(
    project_id: UUID,
    user_id: UUID,
    response: Response,
    session: DbSession,
    principal: CurrentPrincipal,
) -> ProjectMember:
    projects_service.ensure_members_admin(principal, "write")
    provisioning_service.ensure_not_self(principal.user, user_id, "grant_access")
    membership, created = await projects_service.grant_member(
        session,
        project_id,
        user_id,
        granted_by_user_id=principal.user.id,
        studio_id=principal.studio_id,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return _member_out(membership, await session.get(UserModel, user_id))


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Remove a user's access to a project (admin only). Idempotent `204`; "
        "the user's open event streams on this project are closed. Removing "
        "yourself: `403 self_modification_forbidden`. Unknown project or "
        "user: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def revoke_project_member(
    project_id: UUID, user_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> Response:
    projects_service.ensure_members_admin(principal, "write")
    provisioning_service.ensure_not_self(principal.user, user_id, "revoke_access")
    await projects_service.revoke_member(
        session, project_id, user_id, studio_id=principal.studio_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/resolve-repository",
    response_model=ResolveRepositoryResponse,
    description=(
        "Resolve the project linked to the remotes of a local Git repository "
        "(1 to 10 remotes, any URL form). Only projects the caller is a "
        "member of are considered: an unknown repository and one the caller "
        "has no access to both answer `200 {status: not_found}`, identical "
        "in status and body. Remotes matching two projects: `409 ambiguous`. "
        "No valid remote: `422 invalid_repository_url`."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def resolve_repository(
    body: ResolveRepositoryRequest, session: DbSession, principal: CurrentPrincipal
) -> ResolveRepositoryResponse:
    return await project_repositories_service.resolve_repository(session, principal, body.remotes)


@router.post(
    "/{project_id}/repositories",
    response_model=ProjectRepository,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Link a remote repository to a project. Role `admin` or `developer` "
        "with project access; any other role gets `403 forbidden`. The URL "
        "is normalized server-side (invalid URL: `422 "
        "invalid_repository_url`). A remote belongs to at most one project: "
        "linking one owned by another project fails with `409 "
        "repository_already_linked`. Re-linking the same URL to the same "
        "project is a no-op answering `200`. Unknown project: 404."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT: {
            "description": "Remote already linked to another project.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error_code": "repository_already_linked",
                            "message": "repository is already linked to another project",
                            "url": "https://github.com/org/repo",
                        }
                    }
                }
            },
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Repository URL refused, nothing stored (`invalid_repository_url`).",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error_code": "invalid_repository_url",
                            "message": "invalid repository url: 'not-a-url'",
                        }
                    }
                }
            },
        },
    },
)
async def link_project_repository(
    project_id: UUID,
    link_in: ProjectRepositoryCreate,
    response: Response,
    session: DbSession,
    principal: CurrentPrincipal,
) -> ProjectRepository:
    row, created = await project_repositories_service.link_repository(
        session, principal, project_id, link_in.url
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return ProjectRepository(
        project_id=row.project_id,
        url=row.normalized_url,
        created_at=row.created_at,
        created_by=row.created_by,
    )


@router.delete(
    "/{project_id}/repositories/{normalized_url:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Unlink a remote repository from a project. Role `admin` or "
        "`developer` with project access; any other role gets `403 "
        "forbidden`. The path value is re-normalized, so equivalent spellings "
        "match. `204` once removed; a remote that is not linked to the "
        "project answers `404`. Unknown project: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def unlink_project_repository(
    project_id: UUID, normalized_url: str, session: DbSession, principal: CurrentPrincipal
) -> Response:
    removed = await project_repositories_service.unlink_repository(
        session, principal, project_id, normalized_url
    )
    if not removed:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "not_found",
                "message": f"repository {normalized_url} is not linked to project {project_id}",
            },
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
