from __future__ import annotations

import json
import re
from typing import Any

from httpx import AsyncClient
from studio_api.main import app

# UC-2B conformance: the public machine-readable HTTP surface must let a
# previously unknown consumer (unknown-harness / unknown-provider /
# unknown-model, no TECH/*, no DEC-*, no repo docs) authenticate, enumerate
# operations, and respect the main operational constraints — from
# `/openapi.json` alone. Pure schema assertions: no database needed.

FORBIDDEN_FRAGMENTS = (
    "TECH/",
    "DEC-",
    "routers/",
    "services/",
    "studio_api.",
    "studio_mcp",
    ".py::",
    "contract-guardian",
    "studio-tester",
    "studio-architect",
    "sync-debugger",
    "claude",
    "qwen",
    "codex",
    "opencode",
)


def _spec() -> dict[str, Any]:
    return app.openapi()


def _operations() -> dict[tuple[str, str], dict[str, Any]]:
    spec = _spec()
    operations = {}
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if isinstance(operation, dict) and "operationId" in operation:
                operations[(method, path)] = operation
    return operations


def test_bearer_security_scheme_is_declared() -> None:
    schemes = _spec()["components"]["securitySchemes"]
    assert "MachineBearer" in schemes
    scheme = schemes["MachineBearer"]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"
    assert "Authorization" in scheme.get("description", "")
    assert "healthz" in scheme.get("description", "")


_BEARER_EXEMPT = frozenset(
    {
        "/healthz",
        "/version",
        "/api/v1/auth/token",
        "/api/v1/github/webhook",
        "/api/v1/auth/register",
        "/api/v1/auth/resend-verification",
        "/api/v1/auth/verify-email",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
    }
)


def test_all_api_v1_operations_require_bearer_and_healthz_is_exempt() -> None:
    operations = _operations()
    assert operations, "expected documented operations"
    for (method, path), operation in operations.items():
        security = operation.get("security", [])
        if path in _BEARER_EXEMPT:
            # /healthz, GET /version and POST /auth/token predate this step; the
            # GitHub webhook is the deliberate HMAC-signed exception (etape 9.1,
            # DEC-0059) — Bearer-exempt, never unauthenticated. The A4
            # registration/recovery routes are public by design (DEC-0109).
            assert security in ([], None), f"{method} {path} must stay unauthenticated"
        else:
            assert path.startswith("/api/v1"), f"unexpected public path: {path}"
            assert {"MachineBearer": []} in security, f"{method} {path} lacks bearer security"


def test_no_bare_authorization_header_param_remains() -> None:
    for (method, path), operation in _operations().items():
        for param in operation.get("parameters", []):
            assert param.get("name") != "authorization", (
                f"{method} {path} still exposes a bare authorization header param"
            )


def test_idempotency_key_documented_on_replayable_creations() -> None:
    replayable = (
        "/api/v1/tasks",
        "/api/v1/claims",
        "/api/v1/decisions",
        "/api/v1/sessions",
        "/api/v1/ai-work",
        "/api/v1/projects",
        "/api/v1/agents",
        "/api/v1/transfers",
        "/api/v1/producer-jobs",
        "/api/v1/projects/{project_id}/github-integration",
    )
    operations = _operations()
    for path in replayable:
        params = {p["name"]: p for p in operations[("post", path)].get("parameters", [])}
        assert "Idempotency-Key" in params, f"POST {path} misses Idempotency-Key"
        description = params["Idempotency-Key"].get("description", "")
        assert "duplicate" in description
        assert "409" in description or "payload_mismatch" in description


def test_no_idempotency_key_on_events_or_provisioning() -> None:
    operations = _operations()
    post_events = operations[("post", "/api/v1/events")]
    assert "Idempotency-Key" not in {p["name"] for p in post_events.get("parameters", [])}
    assert "event_id" in post_events.get("description", "")
    assert "Idempotency-Key" not in {
        p["name"] for p in operations[("post", "/api/v1/machines")].get("parameters", [])
    }
    assert "Idempotency-Key" not in {
        p["name"] for p in operations[("post", "/api/v1/users")].get("parameters", [])
    }


def test_if_match_version_documented_and_required() -> None:
    operation = _operations()[("patch", "/api/v1/tasks/{task_id}")]
    params = {p["name"]: p for p in operation.get("parameters", [])}
    assert params["If-Match-Version"]["required"] is True
    assert "version_conflict" in params["If-Match-Version"].get("description", "")
    assert "409" in json.dumps(operation["responses"])


def test_forbidden_documented_on_writes() -> None:
    operations = _operations()
    for method, path in (
        ("post", "/api/v1/tasks"),
        ("post", "/api/v1/claims"),
        ("post", "/api/v1/events"),
        ("post", "/api/v1/ai-work"),
        ("post", "/api/v1/transfers"),
        ("post", "/api/v1/agents"),
    ):
        responses = operations[(method, path)]["responses"]
        assert "403" in responses, f"{method} {path} misses 403"
        assert "forbidden" in json.dumps(responses["403"])


def test_actor_not_owned_documented_on_ai_work_creation() -> None:
    responses = _operations()[("post", "/api/v1/ai-work")]["responses"]
    assert "actor_not_owned" in json.dumps(responses.get("409", {}))


def test_event_identity_rules_documented() -> None:
    operation = _operations()[("post", "/api/v1/events")]
    text = operation.get("description", "") + json.dumps(operation["responses"])
    for fragment in (
        "machine_id_mismatch",
        "actor_id_mismatch",
        "actor_not_owned",
        "actor_type",
        "POST /agents",
    ):
        assert fragment in text


def test_event_stream_is_comprehensible() -> None:
    operation = _operations()[("get", "/api/v1/events/stream")]
    responses = operation["responses"]
    assert "text/event-stream" in json.dumps(responses.get("200", {}))
    text = operation.get("description", "") + json.dumps(operation)
    for fragment in ("Last-Event-ID", "since_seq", "seq", "GET /events"):
        assert fragment in text


def test_transfer_cycle_constraints_documented() -> None:
    operations = _operations()
    operation = operations[("post", "/api/v1/transfers")]
    assert "never pass through this API" in operation.get("description", "")
    responses = json.dumps(operation["responses"])
    assert "transfer_too_large" in responses
    assert "quota_exceeded" in responses
    initiate = operations[("post", "/api/v1/transfers/{transfer_id}/upload/initiate")]
    initiate_text = initiate.get("description", "") + json.dumps(initiate["responses"])
    assert "missing_content_md5" in initiate_text
    assert "multipart" in initiate.get("description", "")
    download = operations[("post", "/api/v1/transfers/{transfer_id}/download-url")]
    assert "Range" in download.get("description", "")


def test_agent_registration_needs_nothing_but_documents_provenance() -> None:
    operation = _operations()[("post", "/api/v1/agents")]
    description = operation.get("description", "")
    assert "derived" in description
    assert "no permission" in description


def test_claims_soft_lock_documented() -> None:
    operation = _operations()[("post", "/api/v1/claims")]
    description = operation.get("description", "").lower()
    assert "soft lock" in description
    assert "never block" in description


def test_no_internal_references_leak_into_openapi() -> None:
    blob = json.dumps(_spec()).lower()
    for fragment in FORBIDDEN_FRAGMENTS:
        if fragment == "DEC-":
            # "DEC-XXXX" as a human-readable id format example is public
            # documentation; only numbered decision references (DEC-0041…)
            # count as internal leaks.
            assert not re.search(r"dec-\d", blob), "numbered DEC reference leaked"
        else:
            assert fragment.lower() not in blob, f"internal reference leaked: {fragment}"


async def test_auth_runtime_shapes_match_documentation(client: AsyncClient) -> None:
    """The Bearer migration must not change runtime acceptance: exact 401
    shapes, and /healthz reachable with no credential at all."""
    missing = await client.get("/api/v1/projects")
    assert missing.status_code == 401
    assert missing.json() == {"detail": "missing bearer token"}

    invalid = await client.get("/api/v1/projects", headers={"Authorization": "Bearer nope"})
    assert invalid.status_code == 401
    assert invalid.json() == {"detail": "invalid or revoked machine token"}

    health = await client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_app_description_and_tag_taxonomy_present() -> None:
    spec = _spec()
    assert "Authorization" in spec["info"].get("description", "")
    tags = {tag["name"]: tag.get("description", "") for tag in spec.get("tags", [])}
    for expected in ("tasks", "events", "transfers", "agents", "ai-work", "claims", "health"):
        assert tags.get(expected), f"tag {expected} misses a description"
