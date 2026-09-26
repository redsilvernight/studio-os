from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from studio_contracts.builds import (
    GitHubIntegration,
    GitHubIntegrationCreate,
    GitHubIntegrationUpdate,
    GitHubWebhookResult,
)

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_400_WEBHOOK_MALFORMED,
    RESP_401_UNAUTHORIZED,
    RESP_401_WEBHOOK_SIGNATURE,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
    RESP_413_WEBHOOK_TOO_LARGE,
    RESP_503_WEBHOOK_NOT_CONFIGURED,
)
from studio_api.services import github as github_service
from studio_api.services import idempotency as idempotency_service
from studio_api.settings import get_settings

router = APIRouter(tags=["github"])


async def _read_bounded_body(request: Request, max_bytes: int) -> bytes | None:
    """Streams the body in chunks and stops past `max_bytes` — `await
    request.body()` would buffer an unbounded unauthenticated payload into
    memory before any check runs. Returns None when over the bound."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/api/v1/github/webhook",
    response_model=GitHubWebhookResult,
    description=(
        "GitHub webhook ingress. Authenticated by "
        "`X-Hub-Signature-256` HMAC over the raw body with the process-wide "
        "webhook secret — never a machine Bearer token, so this is a "
        "deliberate signed authentication exception. Unknown event names and "
        "unconfigured repositories answer `202` (accepted-but-ignored), "
        "never `500`."
    ),
    responses={
        **RESP_401_WEBHOOK_SIGNATURE,
        **RESP_503_WEBHOOK_NOT_CONFIGURED,
        **RESP_413_WEBHOOK_TOO_LARGE,
        **RESP_400_WEBHOOK_MALFORMED,
    },
)
async def github_webhook(
    request: Request,
    session: DbSession,
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    x_hub_signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> GitHubWebhookResult | JSONResponse:
    settings = get_settings()
    secret = settings.github_webhook_secret
    if not secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "webhook_not_configured",
                "message": "GitHub webhook ingress is not configured on this server",
            },
        )
    body = await _read_bounded_body(request, settings.github_webhook_max_body_bytes)
    if body is None:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"error_code": "webhook_body_too_large"},
        )
    if not github_service.verify_signature(secret.encode(), body, x_hub_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook signature")
    if not x_github_event or not x_github_delivery:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "webhook_missing_headers"},
        )
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "webhook_invalid_json"},
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "webhook_invalid_json"},
        )

    def _ignored(detail: str | None = None) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=GitHubWebhookResult(
                status="ignored", github_event=x_github_event, detail=detail
            ).model_dump(mode="json"),
        )

    repo = payload.get("repository") or {}
    repo_name = repo.get("full_name") if isinstance(repo, dict) else None
    integration = (
        await github_service.get_integration_by_repo(session, str(repo_name))
        if isinstance(repo_name, str)
        else None
    )
    if integration is None:
        return _ignored("unconfigured_repository")
    outcome = await github_service.ingest_webhook(
        session, integration, x_github_event, x_github_delivery, payload
    )
    if outcome["status"] != "accepted":
        return _ignored(str(outcome.get("github_event") or outcome["status"]))
    raw_build_id = outcome.get("build_id")
    raw_pr_number = outcome.get("pr_number")
    return GitHubWebhookResult(
        status="accepted",
        github_event=x_github_event,
        build_id=UUID(str(raw_build_id)) if isinstance(raw_build_id, str) else None,
        pr_number=raw_pr_number if isinstance(raw_pr_number, int) else None,
    )


@router.post(
    "/api/v1/projects/{project_id}/github-integration",
    response_model=GitHubIntegration,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Wire a project to a GitHub repository. Role `admin` or `developer`. "
        "Accepts `Idempotency-Key` for safe retries."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_IDEMPOTENCY},
)
async def create_github_integration(
    project_id: UUID,
    integration_in: GitHubIntegrationCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> GitHubIntegration:
    if integration_in.project_id != project_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "project_id_mismatch",
                "message": "body project_id must match the path project_id",
            },
        )
    github_service.authorize_integration_write(principal, project_id)

    async def _create() -> GitHubIntegration:
        integration = await github_service.create_integration(session, principal, integration_in)
        return GitHubIntegration.model_validate(integration)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /projects/{project_id}/github-integration",
        GitHubIntegration,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "/api/v1/projects/{project_id}/github-integration",
    response_model=GitHubIntegration,
    description=(
        "Read a project's GitHub wiring. A project the caller cannot access "
        "answers `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_github_integration(
    project_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> GitHubIntegration:
    integration = await github_service.get_integration_for(session, principal, project_id)
    if integration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "github integration not found")
    return GitHubIntegration.model_validate(integration)


@router.patch(
    "/api/v1/projects/{project_id}/github-integration",
    response_model=GitHubIntegration,
    description=(
        "Update a project's GitHub wiring (repository, default branch, "
        "enabled flag). Role `admin` or `developer`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def update_github_integration(
    project_id: UUID,
    integration_in: GitHubIntegrationUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
) -> GitHubIntegration:
    integration = await github_service.get_integration_for(session, principal, project_id, "write")
    if integration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "github integration not found")
    updated = await github_service.update_integration(
        session, principal, integration, integration_in
    )
    return GitHubIntegration.model_validate(updated)
