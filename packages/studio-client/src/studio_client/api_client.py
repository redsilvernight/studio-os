from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from typing import Any, cast
from uuid import UUID

import httpx
from studio_contracts.auth import HeartbeatRequest, HeartbeatResponse
from studio_contracts.events import EventCreate, EventEnvelope
from studio_contracts.project_state import ProjectState
from studio_contracts.projects import Project
from studio_contracts.tasks import Task, TaskCreate

from studio_client.config import ClientConfig
from studio_client.errors import StudioApiError, TransportError, error_from_response
from studio_client.retry import RetryPolicy, is_retryable, sleep
from studio_client.tokens import KeyringTokenStore, TokenStore, origin_of, resolve_token


class StudioApiClient:
    """Bloc B's only sanctioned way to talk to the API (DEC-0024): carries
    the machine Bearer token, propagates a caller-supplied `Idempotency-Key`
    or `event_id` (never generates one itself), retries only what is safe
    to retry, and never proxies file bytes — transfers go straight to
    MinIO/S3 via presigned URLs (out of scope for this client, see
    `docs/ROADMAP_STEP6_BREAKDOWN.md` sous-etape 6.7)."""

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
