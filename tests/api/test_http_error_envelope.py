"""HTTP error-envelope contract across the real 4xx statuses.

Inventory of the real shapes (TECH/02_API_CONTRACT.md, DEC-0024). FastAPI
always wraps `HTTPException.detail`, so a machine-readable error is
`{"detail": {"error_code": "...", ...}}` — never a flat `{"error_code": ...}`.
`error_code` values are stable snake_case tokens, not prose.

Two deliberate, documented exceptions carry no `error_code` and must stay so
(turning them into codes would change an observable contract):
- generic 401 (missing/invalid/revoked credential) is `{"detail": "<string>"}`;
- the framework's native request-validation 422 is `{"detail": [ ... ]}`.

The flat `studio_contracts.common.ErrorResponse`/`VersionConflictError` model
that used to describe a third shape was unused and has been removed; these
tests pin the shapes the server actually returns. No response status or field
is changed here.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel

SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


def _detail(response: Any) -> Any:
    body = response.json()
    assert isinstance(body, dict), body
    assert "detail" in body, body
    assert "error_code" not in body, body
    return body["detail"]


def _machine_readable_detail(response: Any) -> dict[str, Any]:
    detail = _detail(response)
    assert isinstance(detail, dict), detail
    error_code = detail.get("error_code")
    assert isinstance(error_code, str), detail
    assert SNAKE_CASE.match(error_code), error_code
    return detail


async def test_400_carries_a_machine_readable_error_code(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers,
        json={"current_password": "not-the-password", "new_password": "a long enough secret"},
    )
    assert response.status_code == 400
    detail = _machine_readable_detail(response)
    assert detail["error_code"] == "invalid_current_password"


async def test_401_missing_credential_is_the_documented_plain_message(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/machines/me")
    assert response.status_code == 401
    assert _detail(response) == "missing bearer token"


async def test_401_invalid_credential_is_the_documented_plain_message(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/machines/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401
    assert _detail(response) == "invalid or revoked machine token"


async def test_403_carries_resource_and_action(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    response = await client.post(
        "/api/v1/machines",
        headers=auth_headers,
        json={
            "owner_user_id": str(other_machine[0].owner_user_id),
            "display_name": "forged owner",
        },
    )
    assert response.status_code == 403
    detail = _machine_readable_detail(response)
    assert detail == {"error_code": "forbidden", "resource": "machine", "action": "create"}


async def test_409_carries_a_machine_readable_error_code(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = {
        "display_name": "envelope-agent",
        "agent_kind": "",
        "agent_profile": None,
        "harness": "opencode",
        "provider": None,
        "model": None,
        "stable_key": f"envelope-{uuid.uuid4().hex}",
    }
    first = await client.post("/api/v1/agents/ensure", headers=auth_headers, json=body)
    assert first.status_code == 201
    conflict = await client.post(
        "/api/v1/agents/ensure", headers=auth_headers, json={**body, "display_name": "renamed"}
    )
    assert conflict.status_code == 409
    detail = _machine_readable_detail(conflict)
    assert detail["error_code"] == "idempotency_key_payload_mismatch"


async def test_422_domain_refusal_carries_a_machine_readable_error_code(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/library",
        headers=admin_auth_headers,
        json={
            "kind": "rule",
            "stable_key": f"envelope-{uuid.uuid4().hex}",
            "scope": "studio",
            "project_id": str(uuid.uuid4()),
            "title": "scope envelope",
        },
    )
    assert response.status_code == 422
    detail = _machine_readable_detail(response)
    assert detail["error_code"] == "invalid_scope_context"


async def test_422_request_validation_is_the_framework_list_shape(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post("/api/v1/library", headers=auth_headers, json={})
    assert response.status_code == 422
    detail = _detail(response)
    assert isinstance(detail, list) and detail
    assert all(isinstance(item, dict) and "loc" in item for item in detail)
