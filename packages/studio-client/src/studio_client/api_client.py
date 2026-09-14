from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from typing import Any, cast
from uuid import UUID

import httpx
from studio_contracts.auth import HeartbeatRequest, HeartbeatResponse
from studio_contracts.claims import ResourceClaim, ResourceClaimCreate
from studio_contracts.events import EventCreate, EventEnvelope
from studio_contracts.project_state import ProjectState
from studio_contracts.projects import Project
from studio_contracts.sessions import WorkSession, WorkSessionCreate
from studio_contracts.tasks import Task, TaskCreate, TaskUpdate
from studio_contracts.transfers import (
    DownloadUrlResponse,
    Transfer,
    TransferConsumption,
    TransferCreate,
    UploadCompleteRequest,
    UploadInitiateResponse,
)

from studio_client.config import ClientConfig
from studio_client.errors import StudioApiError, TransportError, error_from_response
from studio_client.retry import RetryPolicy, is_retryable, sleep
from studio_client.tokens import KeyringTokenStore, TokenStore, origin_of, resolve_token


class StudioApiClient:
    """Bloc B's only sanctioned way to talk to the API (DEC-0024): carries
    the machine Bearer token, propagates a caller-supplied `Idempotency-Key`
    or `event_id` (never generates one itself), retries only what is safe
    to retry, and never proxies file bytes itself — for transfers it only
    hands out metadata and presigned URLs; `TransferClient` (sous-etape 6.7,
    `docs/ROADMAP_STEP6_BREAKDOWN.md`) talks to MinIO/S3 directly with them."""

    def __init__(
        self,
        config: ClientConfig,
        token_store: TokenStore | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._origin = origin_of(config.api_base_url)
        self._token_store = token_store or KeyringTokenStore()
        self._retry_policy = RetryPolicy(
            config.max_attempts, config.backoff_initial, config.backoff_max
        )
        self._client = httpx.AsyncClient(
            base_url=config.api_base_url,
            timeout=httpx.Timeout(config.read_timeout, connect=config.connect_timeout),
            verify=config.verify_tls,
            transport=transport,
        )

    async def __aenter__(self) -> StudioApiClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _auth_header(self) -> dict[str, str]:
        token = resolve_token(self._origin, stores=[self._token_store])
        return {"Authorization": f"Bearer {token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        authenticated: bool = True,
        idempotent: bool = False,
    ) -> httpx.Response:
        """`idempotent=True` asserts the caller already made this exact call
        safe to repeat — a stable `Idempotency-Key` in `extra_headers`, or a
        stable `event_id` embedded in `json`. Without it, a POST/PATCH/DELETE
        is never retried: a silent retry would risk creating a duplicate."""
        headers = dict(extra_headers or {})
        if authenticated:
            headers.update(self._auth_header())
        can_retry = idempotent or method.upper() in {"GET", "HEAD"}

        attempt = 1
        while True:
            error: StudioApiError
            try:
                response = await self._client.request(
                    method, path, json=json, params=params, headers=headers
                )
            except httpx.TimeoutException:
                error = TransportError(f"timeout calling {method} {path}")
            except httpx.TransportError:
                error = TransportError(f"transport error calling {method} {path}")
            else:
                if response.status_code < 400:
                    return response
                error = error_from_response(response)

            if (
                not can_retry
                or attempt >= self._retry_policy.max_attempts
                or not is_retryable(error)
            ):
                raise error
            await sleep(self._retry_policy.delay_for(attempt))
            attempt += 1

    async def healthz(self) -> dict[str, str]:
        response = await self._request("GET", "/healthz", authenticated=False)
        return cast(dict[str, str], response.json())

    async def list_projects(self) -> list[Project]:
        response = await self._request("GET", "/api/v1/projects")
        return [Project.model_validate(item) for item in response.json()]

    async def get_project_state(self, project_id: UUID) -> ProjectState:
        response = await self._request("GET", f"/api/v1/projects/{project_id}/state")
        return ProjectState.model_validate(response.json())

    async def send_heartbeat(
        self, machine_id: UUID, agent_id: UUID | None = None
    ) -> HeartbeatResponse:
        payload = HeartbeatRequest(
            machine_id=machine_id, agent_id=agent_id, client_timestamp=datetime.now(UTC)
        )
        response = await self._request(
            "POST",
            "/api/v1/heartbeats",
            json=payload.model_dump(mode="json"),
            idempotent=True,
        )
        return HeartbeatResponse.model_validate(response.json())

    async def post_event(self, event: EventCreate) -> EventEnvelope:
        """Idempotent by construction: `event.event_id` is the replay key
        (`TECH/04_AUTH_SYNC_CONTRACT.md`), generated by the caller — never by
        this client (DEC-0024)."""
        response = await self._request(
            "POST",
            "/api/v1/events",
            json=event.model_dump(mode="json"),
            idempotent=True,
        )
        return EventEnvelope.model_validate(response.json())

    async def create_task(self, task_in: TaskCreate, *, idempotency_key: str) -> Task:
        response = await self._request(
            "POST",
            "/api/v1/tasks",
            json=task_in.model_dump(mode="json"),
            extra_headers={"Idempotency-Key": idempotency_key},
            idempotent=True,
        )
        return Task.model_validate(response.json())

    async def list_tasks(
        self, *, project_id: UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[Task]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if project_id is not None:
            params["project_id"] = str(project_id)
        response = await self._request("GET", "/api/v1/tasks", params=params)
        return [Task.model_validate(item) for item in response.json()]

    async def get_task(self, task_id: UUID) -> Task:
        response = await self._request("GET", f"/api/v1/tasks/{task_id}")
        return Task.model_validate(response.json())

    async def update_task(
        self, task_id: UUID, task_in: TaskUpdate, *, if_match_version: int
    ) -> Task:
        """No `Idempotency-Key` support server-side (`TECH/02_API_CONTRACT.md`
        lists only creation endpoints) — never retried automatically."""
        response = await self._request(
            "PATCH",
            f"/api/v1/tasks/{task_id}",
            json=task_in.model_dump(mode="json", exclude_unset=True),
            extra_headers={"If-Match-Version": str(if_match_version)},
        )
        return Task.model_validate(response.json())

    async def claim_task(self, task_id: UUID) -> Task:
        response = await self._request("POST", f"/api/v1/tasks/{task_id}/claim")
        return Task.model_validate(response.json())

    async def release_task(self, task_id: UUID) -> Task:
        response = await self._request("POST", f"/api/v1/tasks/{task_id}/release")
        return Task.model_validate(response.json())

    async def list_sessions(self, *, task_id: UUID | None = None) -> list[WorkSession]:
        params: dict[str, Any] = {}
        if task_id is not None:
            params["task_id"] = str(task_id)
        response = await self._request("GET", "/api/v1/sessions", params=params)
        return [WorkSession.model_validate(item) for item in response.json()]

    async def start_session(
        self, session_in: WorkSessionCreate, *, idempotency_key: str
    ) -> WorkSession:
        response = await self._request(
            "POST",
            "/api/v1/sessions",
            json=session_in.model_dump(mode="json"),
            extra_headers={"Idempotency-Key": idempotency_key},
            idempotent=True,
        )
        return WorkSession.model_validate(response.json())

    async def end_session(self, session_id: UUID) -> WorkSession:
        response = await self._request("PATCH", f"/api/v1/sessions/{session_id}/end")
        return WorkSession.model_validate(response.json())

    async def list_claims(self, *, project_id: UUID | None = None) -> list[ResourceClaim]:
        params: dict[str, Any] = {}
        if project_id is not None:
            params["project_id"] = str(project_id)
        response = await self._request("GET", "/api/v1/claims", params=params)
        return [ResourceClaim.model_validate(item) for item in response.json()]

    async def create_claim(
        self, claim_in: ResourceClaimCreate, *, idempotency_key: str
    ) -> ResourceClaim:
        response = await self._request(
            "POST",
            "/api/v1/claims",
            json=claim_in.model_dump(mode="json"),
            extra_headers={"Idempotency-Key": idempotency_key},
            idempotent=True,
        )
        return ResourceClaim.model_validate(response.json())

    async def renew_claim(self, claim_id: UUID) -> ResourceClaim:
        response = await self._request("POST", f"/api/v1/claims/{claim_id}/renew")
        return ResourceClaim.model_validate(response.json())

    async def release_claim(self, claim_id: UUID) -> None:
        """`DELETE /claims/{id}` returns 204 with no body — never retried
        automatically, same rationale as `update_task`/`claim_task`."""
        await self._request("DELETE", f"/api/v1/claims/{claim_id}")

    async def create_transfer(
        self, transfer_in: TransferCreate, *, idempotency_key: str
    ) -> Transfer:
        response = await self._request(
            "POST",
            "/api/v1/transfers",
            json=transfer_in.model_dump(mode="json"),
            extra_headers={"Idempotency-Key": idempotency_key},
            idempotent=True,
        )
        return Transfer.model_validate(response.json())

    async def list_transfers(self, *, project_id: UUID | None = None) -> list[Transfer]:
        params: dict[str, Any] = {}
        if project_id is not None:
            params["project_id"] = str(project_id)
        response = await self._request("GET", "/api/v1/transfers", params=params)
        return [Transfer.model_validate(item) for item in response.json()]

    async def get_transfer(self, transfer_id: UUID) -> Transfer:
        response = await self._request("GET", f"/api/v1/transfers/{transfer_id}")
        return Transfer.model_validate(response.json())

    async def get_transfer_consumption(
        self, *, project_id: UUID | None = None
    ) -> TransferConsumption:
        params: dict[str, Any] = {}
        if project_id is not None:
            params["project_id"] = str(project_id)
        response = await self._request("GET", "/api/v1/transfers/consumption", params=params)
        return TransferConsumption.model_validate(response.json())

    async def initiate_upload(
        self, transfer_id: UUID, *, content_md5: str | None = None
    ) -> UploadInitiateResponse:
        """Safe to call more than once for the same transfer (re-presigns
        rather than duplicating anything server-side, `transfers.py`
        `initiate_upload`) — marked idempotent so a transient failure can be
        retried. A repeat call still creates a brand-new multipart
        `upload_id` when the transfer is large; `TransferClient` only calls
        this once per upload and resumes against cached part URLs instead
        (sous-etape 6.7)."""
        response = await self._request(
            "POST",
            f"/api/v1/transfers/{transfer_id}/upload/initiate",
            json={"content_md5": content_md5},
            idempotent=True,
        )
        return UploadInitiateResponse.model_validate(response.json())

    async def complete_upload(
        self,
        transfer_id: UUID,
        *,
        size_bytes: int,
        sha256: str,
        upload_id: str | None = None,
        parts: dict[int, str] | None = None,
    ) -> Transfer:
        payload = UploadCompleteRequest(
            size_bytes=size_bytes, sha256=sha256, upload_id=upload_id, parts=parts
        )
        response = await self._request(
            "POST",
            f"/api/v1/transfers/{transfer_id}/upload/complete",
            json=payload.model_dump(mode="json"),
        )
        return Transfer.model_validate(response.json())

    async def get_download_url(self, transfer_id: UUID) -> DownloadUrlResponse:
        response = await self._request("POST", f"/api/v1/transfers/{transfer_id}/download-url")
        return DownloadUrlResponse.model_validate(response.json())

    async def delete_transfer(self, transfer_id: UUID) -> None:
        await self._request("DELETE", f"/api/v1/transfers/{transfer_id}")

    async def send_mutation(
        self, method: str, path: str, payload: dict[str, Any], *, idempotency_key: str
    ) -> httpx.Response:
        """Replays a generically-recorded outbox `pending_mutations` row
        (sous-etape 6.4, docs/ROADMAP_STEP6_BREAKDOWN.md) — same idempotent
        contract as `create_task`, but for a call whose method/path/payload
        only the outbox row itself knows."""
        return await self._request(
            method,
            path,
            json=payload,
            extra_headers={"Idempotency-Key": idempotency_key},
            idempotent=True,
        )
