from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.builds import ProducerJob, ProducerJobRequest

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import producer as producer_service

router = APIRouter(prefix="/api/v1/producer-jobs", tags=["producer"])


@router.post(
    "",
    response_model=ProducerJob,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Run a bounded, synchronous Studio Producer analysis over one "
        "project's shared state. Requires a writer role. Accepts "
        "`Idempotency-Key` for safe retries. The Producer never mutates "
        "tasks or claims: a `decomposition` result is a proposal the caller "
        "materializes via `POST /tasks`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_IDEMPOTENCY},
)
async def request_producer_job(
    job_in: ProducerJobRequest,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> ProducerJob:
    async def _create() -> ProducerJob:
        job = await producer_service.request_producer_job(session, principal, job_in)
        return ProducerJob.model_validate(job)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /producer-jobs",
        ProducerJob,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "",
    response_model=list[ProducerJob],
    description="List Producer jobs, newest first. Any authenticated machine may read.",
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_producer_jobs(
    session: DbSession,
    machine: CurrentMachine,
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[ProducerJob]:
    jobs = await producer_service.list_producer_jobs(session, project_id=project_id, limit=limit)
    return [ProducerJob.model_validate(j) for j in jobs]


@router.get(
    "/{job_id}",
    response_model=ProducerJob,
    description="Get one Producer job by id. Any authenticated machine may read.",
    responses={**RESP_401_UNAUTHORIZED, **RESP_404_NOT_FOUND},
)
async def get_producer_job(
    job_id: UUID, session: DbSession, machine: CurrentMachine
) -> ProducerJob:
    job = await producer_service.get_producer_job(session, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "producer job not found")
    return ProducerJob.model_validate(job)
