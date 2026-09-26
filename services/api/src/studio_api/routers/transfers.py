from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Header, Query, Request, status
from studio_contracts.transfers import (
    DownloadUrlResponse,
    Transfer,
    TransferConsumption,
    TransferCreate,
    UploadCompleteRequest,
    UploadInitiateRequest,
    UploadInitiateResponse,
    UploadPartsRefreshRequest,
    UploadPartsRefreshResponse,
)

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
    RESP_409_TRANSFER_STATE,
    RESP_413_TRANSFER_TOO_LARGE,
    RESP_422_TRANSFER_INTEGRITY,
    RESP_507_QUOTA_EXCEEDED,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import projects as projects_service
from studio_api.services import transfers as transfers_service
from studio_api.settings import get_settings
from studio_api.storage.provider import get_storage

router = APIRouter(prefix="/api/v1/transfers", tags=["transfers"])


@router.get(
    "",
    response_model=list[Transfer],
    description=(
        "List transfer metadata visible to the caller (sender, recipient, "
        "broadcast, or privileged role). The list silently omits "
        "inaccessible transfers instead of erroring."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_transfers(
    session: DbSession, principal: CurrentPrincipal, project_id: UUID | None = Query(default=None)
) -> list[Transfer]:
    transfers = await transfers_service.list_transfers(session, principal, project_id=project_id)
    return [Transfer.model_validate(t) for t in transfers]


@router.post(
    "",
    response_model=Transfer,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Start a transfer: declares filename, size and participants, and "
        "reserves quota. Requires a writer role. Accepts `Idempotency-Key` "
        "for safe retries. File bytes never pass through this API: the "
        "next steps hand back short-lived signed URLs, and the client "
        "uploads directly to object storage. Oversize files fail with "
        "`413 transfer_too_large`; an exhausted quota fails with `507 "
        "quota_exceeded` (check `GET /transfers/consumption` first for "
        "large uploads)."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_409_IDEMPOTENCY,
        **RESP_413_TRANSFER_TOO_LARGE,
        **RESP_507_QUOTA_EXCEEDED,
    },
)
async def create_transfer(
    transfer_in: TransferCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> Transfer:
    # Ahead of the idempotency replay short-circuit (DEC-0036, DEC-0103 §12).
    transfers_service.authorize_create(principal, transfer_in.project_id)
    if transfer_in.project_id is None:
        project_slug = "unscoped"
    else:
        project = await projects_service.get_project(session, principal, transfer_in.project_id)
        project_slug = project.slug

    async def _create() -> Transfer:
        transfer = await transfers_service.create_transfer(
            session, principal, get_settings(), transfer_in, project_slug
        )
        return Transfer.model_validate(transfer)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /transfers",
        Transfer,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "/consumption",
    response_model=TransferConsumption,
    description=(
        "Read quota consumption (`consumed_bytes`, `quota_bytes`, "
        "`remaining_bytes`) for a project, or for the unscoped bucket "
        "when no project is given. Requires access to the project (or, "
        "for the unscoped bucket, at least one project), else `403 "
        "forbidden`. "
        "Call before a large upload to avoid a rejected creation — the "
        "reading is advisory, another upload may still win the race."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def get_consumption(
    session: DbSession, principal: CurrentPrincipal, project_id: UUID | None = Query(default=None)
) -> TransferConsumption:
    transfers_service.ensure_transfer_scope(principal, project_id)
    settings = get_settings()
    consumed = await transfers_service.compute_consumption(session, project_id)
    quota = settings.transfer_project_quota_bytes
    return TransferConsumption(
        project_id=project_id,
        consumed_bytes=consumed,
        quota_bytes=quota,
        remaining_bytes=max(quota - consumed, 0),
    )


@router.get(
    "/{transfer_id}",
    response_model=Transfer,
    description=(
        "Get one transfer's metadata. Only the sender, the recipient, "
        "broadcast recipients, or a privileged role may read it — anyone "
        "else receives `403 forbidden`, never 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_transfer(
    transfer_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> Transfer:
    transfer = await transfers_service.get_transfer(session, principal, transfer_id)
    return Transfer.model_validate(transfer)


@router.post(
    "/{transfer_id}/upload/initiate",
    response_model=UploadInitiateResponse,
    description=(
        "Begin the byte upload and receive signed URL(s) valid for "
        "minutes. Two paths: small files use a single direct upload — "
        "send the file's MD5 (base64) as `content_md5`, it is embedded "
        "in the signed URL and storage itself rejects mismatched bytes "
        "(`422 missing_content_md5` when omitted); large files use "
        "multipart upload in 64-128 MiB chunks, each part going straight "
        "to storage. Only the sender (or a privileged role) may upload. "
        "Keep completed part numbers and their ETags locally so an "
        "interrupted multipart upload resumes without re-sending "
        "finished parts. Re-initiating an already `ready` transfer "
        "fails — completed uploads are never replaceable."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_TRANSFER_STATE,
        **RESP_422_TRANSFER_INTEGRITY,
    },
)
async def initiate_upload(
    transfer_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    body: UploadInitiateRequest | None = Body(default=None),
) -> UploadInitiateResponse:
    transfer = await transfers_service.get_transfer(session, principal, transfer_id)
    settings = get_settings()
    storage = get_storage()
    content_md5 = body.content_md5 if body else None
    return await transfers_service.initiate_upload(
        session, principal, storage, settings, transfer, content_md5
    )


@router.post(
    "/{transfer_id}/upload/refresh-parts",
    response_model=UploadPartsRefreshResponse,
    description=(
        "Resume helper for an interrupted multipart upload: reports which "
        "parts storage already holds (server truth) and re-signs URLs "
        "for the missing parts only. Adopt the returned part list as the "
        "new local state. An unknown `upload_id` means the server-side "
        "upload is gone — discard local state and restart from "
        "`upload/initiate`."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_TRANSFER_STATE,
        **RESP_422_TRANSFER_INTEGRITY,
    },
)
async def refresh_upload_parts(
    transfer_id: UUID,
    body: UploadPartsRefreshRequest,
    session: DbSession,
    principal: CurrentPrincipal,
) -> UploadPartsRefreshResponse:
    transfer = await transfers_service.get_transfer(session, principal, transfer_id)
    settings = get_settings()
    storage = get_storage()
    return await transfers_service.refresh_upload_parts(
        session,
        principal,
        storage,
        settings,
        transfer,
        body.upload_id,
        body.part_size_bytes,
        body.part_numbers,
    )


@router.post(
    "/{transfer_id}/upload/complete",
    response_model=Transfer,
    description=(
        "Finish the upload and mark the transfer `ready`. The declared "
        "size must equal the size given at creation (the value quota was "
        "checked against), and on the single-upload path the stored "
        "bytes are re-verified against the presigned checksum — any "
        "divergence fails instead of silently marking ready. Only the "
        "sender (or a privileged role) may complete."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_422_TRANSFER_INTEGRITY,
    },
)
async def complete_upload(
    transfer_id: UUID, body: UploadCompleteRequest, session: DbSession, principal: CurrentPrincipal
) -> Transfer:
    transfer = await transfers_service.get_transfer(session, principal, transfer_id)
    storage = get_storage()
    transfer = await transfers_service.complete_upload(
        session,
        principal,
        storage,
        transfer,
        body.size_bytes,
        body.sha256,
        body.upload_id,
        body.parts,
    )
    return Transfer.model_validate(transfer)


@router.post(
    "/{transfer_id}/download-url",
    response_model=DownloadUrlResponse,
    description=(
        "Get a short-lived presigned download URL (minutes, never the "
        "file bytes). Only the sender, the recipient, broadcast "
        "recipients, or a privileged role may obtain it. Downloads "
        "support HTTP `Range`, so a partial download resumes where it "
        "stopped."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_download_url(
    transfer_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> DownloadUrlResponse:
    transfer = await transfers_service.get_transfer(session, principal, transfer_id)
    settings = get_settings()
    storage = get_storage()
    url, expires_at = transfers_service.get_download_url(storage, settings, transfer)
    return DownloadUrlResponse(transfer_id=transfer.id, download_url=url, expires_at=expires_at)


@router.delete(
    "/{transfer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Delete a transfer and its stored bytes. Only the sender (or a "
        "privileged role) may delete. Non-expired transfers are never "
        "removed automatically."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def delete_transfer(
    transfer_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> None:
    transfer = await transfers_service.get_transfer(session, principal, transfer_id)
    storage = get_storage()
    await transfers_service.delete_transfer(session, principal, storage, transfer)
