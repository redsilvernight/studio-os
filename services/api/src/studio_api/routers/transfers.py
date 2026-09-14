from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request, status
from studio_contracts.transfers import (
    DownloadUrlResponse,
    Transfer,
    TransferConsumption,
    TransferCreate,
    UploadCompleteRequest,
    UploadInitiateRequest,
    UploadInitiateResponse,
)

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.services import idempotency as idempotency_service
from studio_api.services import projects as projects_service
from studio_api.services import transfers as transfers_service
from studio_api.services.authz import ensure_can_write
from studio_api.settings import get_settings
from studio_api.storage.provider import get_storage

router = APIRouter(prefix="/api/v1/transfers", tags=["transfers"])


@router.get("", response_model=list[Transfer])
async def list_transfers(
    session: DbSession, principal: CurrentPrincipal, project_id: UUID | None = Query(default=None)
) -> list[Transfer]:
    transfers = await transfers_service.list_transfers(session, principal, project_id=project_id)
    return [Transfer.model_validate(t) for t in transfers]


@router.post("", response_model=Transfer, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    transfer_in: TransferCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Transfer:
    """Runs unconditionally, ahead of `run_idempotent`'s replay
    short-circuit — see `routers/tasks.py::create_task` for why (DEC-0036)."""
    ensure_can_write(principal, "transfer")

    async def _create() -> Transfer:
        if transfer_in.project_id is None:
            project_slug = "unscoped"
        else:
            project = await projects_service.get_project(session, transfer_in.project_id)
            if project is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
            project_slug = project.slug

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


@router.get("/consumption", response_model=TransferConsumption)
async def get_consumption(
    session: DbSession, machine: CurrentMachine, project_id: UUID | None = Query(default=None)
) -> TransferConsumption:
    settings = get_settings()
    consumed = await transfers_service.compute_consumption(session, project_id)
    quota = settings.transfer_project_quota_bytes
    return TransferConsumption(
        project_id=project_id,
        consumed_bytes=consumed,
        quota_bytes=quota,
        remaining_bytes=max(quota - consumed, 0),
    )


@router.get("/{transfer_id}", response_model=Transfer)
async def get_transfer(
    transfer_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> Transfer:
    transfer = await transfers_service.get_transfer(session, principal, transfer_id)
    return Transfer.model_validate(transfer)


@router.post("/{transfer_id}/upload/initiate", response_model=UploadInitiateResponse)
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


@router.post("/{transfer_id}/upload/complete", response_model=Transfer)
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


@router.post("/{transfer_id}/download-url", response_model=DownloadUrlResponse)
async def get_download_url(
    transfer_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> DownloadUrlResponse:
    transfer = await transfers_service.get_transfer(session, principal, transfer_id)
    settings = get_settings()
    storage = get_storage()
    url, expires_at = transfers_service.get_download_url(storage, settings, transfer)
    return DownloadUrlResponse(transfer_id=transfer.id, download_url=url, expires_at=expires_at)


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transfer(
    transfer_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> None:
    transfer = await transfers_service.get_transfer(session, principal, transfer_id)
    storage = get_storage()
    await transfers_service.delete_transfer(session, principal, storage, transfer)
