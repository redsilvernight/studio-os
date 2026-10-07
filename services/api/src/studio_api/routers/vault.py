from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from studio_contracts.vault import (
    VAULT_SEARCH_LIMIT_DEFAULT,
    VAULT_SEARCH_LIMIT_MAX,
    VAULT_SEARCH_MAX_CHARS_DEFAULT,
    VAULT_SEARCH_MAX_CHARS_MAX,
    VAULT_SEARCH_PATHS_MAX,
    VaultNote,
    VaultNoteCreate,
    VaultNoteStatus,
    VaultNoteType,
    VaultNoteUpdate,
    VaultNoteVersion,
    VaultScope,
    VaultSearchResult,
    VaultTreePage,
    VaultVersionPage,
)

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
    RESP_409_VAULT_SLUG,
    RESP_409_VERSION_CONFLICT,
    RESP_422_VAULT,
    merge_conflict,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import vault as vault_service

router = APIRouter(prefix="/api/v1/vault", tags=["vault"])


@router.post(
    "/notes",
    response_model=VaultNote,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create a vault note. The server assigns `id`, `version`, "
        "`content_hash` and the author (the caller's user); a `decision` note "
        "also gets a `readable_id` from the shared DEC sequence. A slug already "
        "taken by a non-archived note of the same scope is `409 "
        "vault_slug_conflict`. Accepts `Idempotency-Key` for safe retries."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **merge_conflict(RESP_409_IDEMPOTENCY, RESP_409_VAULT_SLUG),
        **RESP_422_VAULT,
    },
)
async def create_note(
    note_in: VaultNoteCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> VaultNote:
    vault_service.authorize_create(principal, note_in)

    async def _create() -> VaultNote:
        note = await vault_service.create_note(session, principal, note_in)
        return await vault_service.serialize_note(session, note)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /vault/notes",
        VaultNote,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "/notes/{note_id}",
    response_model=VaultNote,
    description=(
        "Get one vault note by id, links included. A project note the caller "
        "cannot access answers `403 forbidden` (resource `project`)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_note(note_id: UUID, session: DbSession, principal: CurrentPrincipal) -> VaultNote:
    note = await vault_service.read_note(session, principal, note_id)
    return await vault_service.serialize_note(session, note)


@router.patch(
    "/notes/{note_id}",
    response_model=VaultNote,
    description=(
        "Mutate a vault note. `expected_version` is mandatory; a stale value is "
        "rejected with the live server version. Scope, project and slug never "
        "change. No DELETE exists: archiving is a `status` write."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_VERSION_CONFLICT,
        **RESP_422_VAULT,
    },
)
async def update_note(
    note_id: UUID,
    note_in: VaultNoteUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
) -> VaultNote:
    note = await vault_service.update_note(session, principal, note_id, note_in)
    return await vault_service.serialize_note(session, note)


@router.get(
    "/notes/{note_id}/versions",
    response_model=VaultVersionPage,
    description=(
        "List a note's immutable history, oldest version first. Every accepted "
        "write (creation included) appends one version. Paginated with an "
        "opaque cursor."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def list_versions(
    note_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> VaultVersionPage:
    return await vault_service.list_versions(session, principal, note_id, limit, cursor)


@router.get(
    "/notes/{note_id}/versions/{version}",
    response_model=VaultNoteVersion,
    description="Get one immutable version of a note by its version number.",
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_version(
    note_id: UUID, version: int, session: DbSession, principal: CurrentPrincipal
) -> VaultNoteVersion:
    return await vault_service.get_version(session, principal, note_id, version)


@router.get(
    "/tree",
    response_model=VaultTreePage,
    description=(
        "List vault notes as summaries (no `body`), ordered by slug, with an "
        "opaque keyset cursor. `scope` narrows to studio or project (project "
        "requires `project_id`); without a scope, a caller sees studio notes "
        "plus the notes of its accessible projects. Archived notes are "
        "excluded unless `include_archived`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def tree(
    session: DbSession,
    principal: CurrentPrincipal,
    scope: VaultScope | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    prefix: str | None = Query(default=None),
    status_filter: VaultNoteStatus | None = Query(default=None, alias="status"),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> VaultTreePage:
    return await vault_service.list_tree(
        session,
        principal,
        scope,
        project_id,
        prefix,
        status_filter,
        include_archived,
        limit,
        cursor,
    )


@router.get(
    "/search",
    response_model=VaultSearchResult,
    description=(
        "Ranked search over the vault notes the caller may read. Criteria: `q` "
        "(full text, French stemming, words OR-ed), `path` (repeatable, "
        "repo-relative) and `task_id` (anchors); at least one is required (422 "
        "`missing_search_criteria`). Order: notes anchored to a requested path "
        "(or an enclosing directory) or task first, then notes one link away "
        "from them, then full-text matches; inside a group by lexical rank, "
        "status (validated first), recency. Filters: `scope`, `project_id` "
        "(studio notes plus that project's), `note_type` and `status` "
        "(repeatable, OR). Superseded notes are excluded unless "
        "`include_superseded` or an explicit `status`; archived ones unless an "
        "explicit `status`. Hits carry the summary and a short snippet, never "
        "the body; `max_chars` caps the answer's text."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_422_VAULT},
)
async def search(
    session: DbSession,
    principal: CurrentPrincipal,
    q: str | None = Query(default=None, max_length=1000),
    scope: VaultScope | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    note_type: list[VaultNoteType] = Query(default_factory=list),
    status_filter: list[VaultNoteStatus] = Query(default_factory=list, alias="status"),
    include_superseded: bool = Query(default=False),
    path: list[str] = Query(default_factory=list, max_length=VAULT_SEARCH_PATHS_MAX),
    task_id: UUID | None = Query(default=None),
    limit: int = Query(default=VAULT_SEARCH_LIMIT_DEFAULT, ge=1, le=VAULT_SEARCH_LIMIT_MAX),
    max_chars: int = Query(
        default=VAULT_SEARCH_MAX_CHARS_DEFAULT, ge=500, le=VAULT_SEARCH_MAX_CHARS_MAX
    ),
) -> VaultSearchResult:
    return await vault_service.search_notes(
        session,
        principal,
        q=q,
        scope=scope,
        project_id=project_id,
        note_types=note_type,
        statuses=status_filter,
        include_superseded=include_superseded,
        paths=path,
        task_id=task_id,
        limit=limit,
        max_chars=max_chars,
    )
