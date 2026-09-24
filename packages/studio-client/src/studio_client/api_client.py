from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from typing import Any, cast
from uuid import UUID

import httpx
from studio_contracts.ai_work import AIWorkLog
from studio_contracts.auth import HeartbeatRequest, HeartbeatResponse, Machine
from studio_contracts.builds import (
    Build,
    BuildStatus,
    ProducerJob,
    ProducerJobRequest,
)
from studio_contracts.claims import ResourceClaim, ResourceClaimCreate
from studio_contracts.decisions import Decision
from studio_contracts.events import EventCreate, EventEnvelope
from studio_contracts.library import LibraryProjectLock, LibraryResource, LibraryVersion
from studio_contracts.project_state import ProjectState
from studio_contracts.projects import Project
from studio_contracts.resolution import AgentResolutionRequest, ResolvedAgentDefinition
from studio_contracts.review_queue import ReviewQueue
from studio_contracts.sessions import WorkSession, WorkSessionCreate
from studio_contracts.tasks import Task, TaskCreate, TaskUpdate
from studio_contracts.timeline import Timeline
from studio_contracts.transfers import (
    DownloadUrlResponse,
    Transfer,
    TransferConsumption,
    TransferCreate,
    UploadCompleteRequest,
    UploadInitiateResponse,
    UploadPartsRefreshRequest,
    UploadPartsRefreshResponse,
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

    async def get_own_machine(self) -> Machine:
        response = await self._request("GET", "/api/v1/machines/me")
        return Machine.model_validate(response.json())

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

    async def list_ai_work(
        self, *, project_id: UUID | None = None, task_id: UUID | None = None
    ) -> list[AIWorkLog]:
        params: dict[str, Any] = {}
        if project_id is not None:
            params["project_id"] = str(project_id)
        if task_id is not None:
            params["task_id"] = str(task_id)
        response = await self._request("GET", "/api/v1/ai-work", params=params)
        return [AIWorkLog.model_validate(item) for item in response.json()]

    async def list_decisions(self, *, project_id: UUID | None = None) -> list[Decision]:
        params: dict[str, Any] = {}
        if project_id is not None:
            params["project_id"] = str(project_id)
        response = await self._request("GET", "/api/v1/decisions", params=params)
        return [Decision.model_validate(item) for item in response.json()]

    async def list_events(
        self,
        *,
        project_id: UUID | None = None,
        task_id: UUID | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[EventEnvelope]:
        params: dict[str, Any] = {"limit": limit}
        if project_id is not None:
            params["project"] = str(project_id)
        if task_id is not None:
            params["task"] = str(task_id)
        if since is not None:
            params["since"] = since.isoformat()
        response = await self._request("GET", "/api/v1/events", params=params)
        return [EventEnvelope.model_validate(item) for item in response.json()]

    async def get_review_queue(
        self, *, project_id: UUID | None = None, conflict_window_hours: int | None = None
    ) -> ReviewQueue:
        params: dict[str, Any] = {}
        if project_id is not None:
            params["project_id"] = str(project_id)
        if conflict_window_hours is not None:
            params["conflict_window_hours"] = conflict_window_hours
        response = await self._request("GET", "/api/v1/review-queue", params=params)
        return ReviewQueue.model_validate(response.json())

    async def list_builds(
        self,
        *,
        project_id: UUID | None = None,
        status: BuildStatus | None = None,
        limit: int = 100,
    ) -> list[Build]:
        params: dict[str, Any] = {"limit": limit}
        if project_id is not None:
            params["project_id"] = str(project_id)
        if status is not None:
            params["status"] = status.value
        response = await self._request("GET", "/api/v1/builds", params=params)
        return [Build.model_validate(item) for item in response.json()]

    async def get_build(self, build_id: UUID) -> Build:
        response = await self._request("GET", f"/api/v1/builds/{build_id}")
        return Build.model_validate(response.json())

    async def request_producer_job(
        self, job_in: ProducerJobRequest, *, idempotency_key: str
    ) -> ProducerJob:
        response = await self._request(
            "POST",
            "/api/v1/producer-jobs",
            json=job_in.model_dump(mode="json"),
            extra_headers={"Idempotency-Key": idempotency_key},
            idempotent=True,
        )
        return ProducerJob.model_validate(response.json())

    async def list_producer_jobs(
        self, *, project_id: UUID | None = None, limit: int = 100
    ) -> list[ProducerJob]:
        params: dict[str, Any] = {"limit": limit}
        if project_id is not None:
            params["project_id"] = str(project_id)
        response = await self._request("GET", "/api/v1/producer-jobs", params=params)
        return [ProducerJob.model_validate(item) for item in response.json()]

    async def get_timeline(
        self,
        project_id: UUID,
        *,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> Timeline:
        params: dict[str, Any] = {"project_id": str(project_id)}
        if since is not None:
            params["since"] = since.isoformat()
        if limit is not None:
            params["limit"] = limit
        response = await self._request("GET", "/api/v1/timeline", params=params)
        return Timeline.model_validate(response.json())

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

    async def refresh_upload_parts(
        self,
        transfer_id: UUID,
        *,
        upload_id: str,
        part_size_bytes: int | None = None,
        part_numbers: list[int] | None = None,
    ) -> UploadPartsRefreshResponse:
        """Re-presigns the still-missing parts of `upload_id` (DEC-0037) —
        pure presign, safe to retry, marked idempotent."""
        payload = UploadPartsRefreshRequest(
            upload_id=upload_id, part_size_bytes=part_size_bytes, part_numbers=part_numbers
        )
        response = await self._request(
            "POST",
            f"/api/v1/transfers/{transfer_id}/upload/refresh-parts",
            json=payload.model_dump(mode="json"),
            idempotent=True,
        )
        return UploadPartsRefreshResponse.model_validate(response.json())

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

    async def list_library_resources(
        self,
        *,
        kind: str | None = None,
        scope: str | None = None,
        project_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[LibraryResource]:
        """Read-only Library listing over the P7 HTTP surface
        (`GET /api/v1/library`, DEC-0071). Pure GET: safe to retry, never
        mutates, never resolves shadowing — the caller selects the effective
        definition from the visible rows (P9/DEC-0073)."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if kind is not None:
            params["kind"] = kind
        if scope is not None:
            params["scope"] = scope
        if project_id is not None:
            params["project_id"] = str(project_id)
        response = await self._request("GET", "/api/v1/library", params=params)
        return [LibraryResource.model_validate(item) for item in response.json()]

    async def get_library_resource(self, resource_id: UUID) -> LibraryResource:
        response = await self._request("GET", f"/api/v1/library/{resource_id}")
        return LibraryResource.model_validate(response.json())

    async def list_library_versions(self, resource_id: UUID) -> list[LibraryVersion]:
        response = await self._request("GET", f"/api/v1/library/{resource_id}/versions")
        return [LibraryVersion.model_validate(item) for item in response.json()]

    async def list_library_locks(
        self, *, project_id: UUID | None = None
    ) -> list[LibraryProjectLock]:
        params: dict[str, Any] = {}
        if project_id is not None:
            params["project_id"] = str(project_id)
        response = await self._request("GET", "/api/v1/library-locks", params=params)
        return [LibraryProjectLock.model_validate(item) for item in response.json()]

    async def resolve_agent(
        self, stable_key: str, *, project_id: UUID | None = None
    ) -> ResolvedAgentDefinition:
        """Resolves one `AgentDefinition` to its canonical
        `ResolvedAgentDefinition` over the P7 HTTP surface
        (`POST /api/v1/resolutions`, DEC-0071). Pure read: the route never
        persists anything, so the call is marked safe to retry. The result
        is harness-neutral — P10 adapters project it locally."""
        payload = AgentResolutionRequest(stable_key=stable_key, project_id=project_id)
        response = await self._request(
            "POST",
            "/api/v1/resolutions",
            json=payload.model_dump(mode="json"),
            idempotent=True,
        )
        return ResolvedAgentDefinition.model_validate(response.json())

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
