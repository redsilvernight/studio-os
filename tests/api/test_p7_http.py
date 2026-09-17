"""P7 HTTP canonique — contract tests (real Postgres, ASGI transport).

Proves the HTTP boundary over the P4/P5/P6 services without re-testing
their business logic: thin routes, explicit Pydantic contracts, auth,
ownership/filter-first, versioning, P0 idempotency, secrets, OpenAPI.
Library routes are reused as-is (no duplicate) — only asserted as present.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import library as library_service
from studio_api.services import runtime_bindings as bindings_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
    RuntimeCapabilities,
)
from studio_contracts.runtime import RuntimeBindingCreate, RuntimeLevel, RuntimeTarget

AGENT = LibraryKind.AGENT_DEFINITION
RULE = LibraryKind.RULE
SKILL = LibraryKind.SKILL
PROFILE = LibraryKind.MODEL_PROFILE


def _key() -> str:
    return uuid.uuid4().hex[:12]


async def _principal(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> Principal:
    return await load_principal(db_session, machine[0])


async def _create(
    db_session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    key: str,
    content: dict[str, object],
    dependencies: list[DependencyPin] | None = None,
    scope: LibraryScope = LibraryScope.STUDIO,
):
    resource, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=kind,
            stable_key=key,
            scope=scope,
            title=f"{key} title",
            content=content,
            dependencies=dependencies or [],
        ),
    )
    await db_session.refresh(resource)
    await library_service.activate_resource_version(
        db_session, principal, resource, 1, resource.version
    )
    await db_session.refresh(resource)
    return resource


def _agent_content() -> dict[str, object]:
    return {"content_schema": "studio.library.agent_definition/v1", "summary": "P7 gate."}


def _profile_content(**requirements: object) -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": dict(requirements),
        "description": "P7 gate.",
    }


async def _gate_world(
    db_session: AsyncSession,
    principal: Principal,
    agent_key: str,
    profile_key: str,
    profile_requirements: dict[str, object],
) -> None:
    await _create(
        db_session, principal, PROFILE, profile_key, _profile_content(**profile_requirements)
    )
    await _create(
        db_session,
        principal,
        AGENT,
        agent_key,
        _agent_content(),
        dependencies=[DependencyPin(kind=PROFILE, stable_key=profile_key, version=1)],
    )


def _binding_body(
    level: str,
    stable_key: str,
    target: dict[str, Any],
    project_id: UUID | None = None,
    kind: str = "agent_definition",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "level": level,
        "target_kind": kind,
        "target_stable_key": stable_key,
        "target": target,
    }
    if project_id is not None:
        body["project_id"] = str(project_id)
    return body


# ---------------------------------------------------------------------------
# Runtime Bindings HTTP
# ---------------------------------------------------------------------------


async def test_bindings_create_get_list_delete(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
) -> None:
    key = _key()
    create = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", key, {"machine_id": str(machine[0].id)}),
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    binding = create.json()
    assert binding["level"] == "user"
    assert binding["target_stable_key"] == key

    get = await client.get(f"/api/v1/runtime-bindings/{binding['id']}", headers=auth_headers)
    assert get.status_code == 200
    assert get.json()["id"] == binding["id"]

    listed = await client.get(
        "/api/v1/runtime-bindings", params={"stable_key": key}, headers=auth_headers
    )
    assert listed.status_code == 200
    assert [b["id"] for b in listed.json()] == [binding["id"]]

    deleted = await client.delete(f"/api/v1/runtime-bindings/{binding['id']}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["id"] == binding["id"]

    gone = await client.get(f"/api/v1/runtime-bindings/{binding['id']}", headers=auth_headers)
    assert gone.status_code == 404


async def test_bindings_isolation_filter_first(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    key = _key()
    create = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", key, {"machine_id": str(machine[0].id)}),
        headers=auth_headers,
    )
    assert create.status_code == 201
    binding_id = create.json()["id"]

    assert (
        await client.get(f"/api/v1/runtime-bindings/{binding_id}", headers=other_auth_headers)
    ).status_code == 404
    others = await client.get(
        "/api/v1/runtime-bindings", params={"stable_key": key}, headers=other_auth_headers
    )
    assert others.status_code == 200
    assert others.json() == []
    assert (
        await client.delete(f"/api/v1/runtime-bindings/{binding_id}", headers=other_auth_headers)
    ).status_code == 404


async def test_bindings_rejects_session_level_and_unknown_kind(
    client: AsyncClient, machine: tuple[MachineModel, str], auth_headers: dict[str, str]
) -> None:
    session_level = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("session", _key(), {"machine_id": str(machine[0].id)}),
        headers=auth_headers,
    )
    assert session_level.status_code == 422
    assert session_level.json()["detail"]["error_code"] == "invalid_runtime_binding"

    bad_kind = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", _key(), {"machine_id": str(machine[0].id)}, kind="rule"),
        headers=auth_headers,
    )
    assert bad_kind.status_code == 422


async def test_bindings_target_gates_and_duplicates(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    other_id = str(other_machine[0].id)
    foreign = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", _key(), {"machine_id": other_id}),
        headers=auth_headers,
    )
    assert foreign.status_code == 403

    unknown = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", _key(), {"machine_id": str(uuid.uuid4())}),
        headers=auth_headers,
    )
    assert unknown.status_code == 404

    key = _key()
    first = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", key, {"machine_id": str(machine[0].id)}),
        headers=auth_headers,
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", key, {"machine_id": str(machine[0].id)}),
        headers=auth_headers,
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "already_bound"


async def test_bindings_auth_and_roles(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
) -> None:
    assert (await client.get("/api/v1/runtime-bindings")).status_code == 401
    denied = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", _key(), {"machine_id": str(machine[0].id)}),
        headers=readonly_auth_headers,
    )
    assert denied.status_code == 403

    studio = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("studio_default", _key(), {"model_ref": "shared-model"}),
        headers=auth_headers,
    )
    assert studio.status_code == 201, studio.text


async def test_bindings_idempotency_p0(
    client: AsyncClient, machine: tuple[MachineModel, str], auth_headers: dict[str, str]
) -> None:
    key = _key()
    body = _binding_body("user", key, {"machine_id": str(machine[0].id)})
    headers = {**auth_headers, "Idempotency-Key": f"p7-bind-{key}"}
    first = await client.post("/api/v1/runtime-bindings", json=body, headers=headers)
    assert first.status_code == 201
    replay = await client.post("/api/v1/runtime-bindings", json=body, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    other_body = _binding_body("user", _key(), {"machine_id": str(machine[0].id)})
    conflict = await client.post("/api/v1/runtime-bindings", json=other_body, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"


async def test_bindings_runtime_id_reference(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
    other_auth_headers: dict[str, str],
) -> None:
    other_principal = await _principal(db_session, other_machine)
    from studio_api.services import runtime_registry as registry_service
    from studio_contracts.runtime import RuntimeRegistrationCreate

    foreign = await registry_service.register_runtime(
        db_session, other_principal, RuntimeRegistrationCreate(provider_ref="p", model_ref="m")
    )
    denied = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", _key(), {"runtime_id": str(foreign.id)}),
        headers=auth_headers,
    )
    assert denied.status_code == 403

    own = await client.post(
        "/api/v1/runtimes",
        json={"provider_ref": "p7", "model_ref": "m7"},
        headers=other_auth_headers,
    )
    assert own.status_code == 201
    linked = await client.post(
        "/api/v1/runtime-bindings",
        json=_binding_body("user", _key(), {"runtime_id": own.json()["id"]}),
        headers=other_auth_headers,
    )
    assert linked.status_code == 201, linked.text


# ---------------------------------------------------------------------------
# Runtime Registry HTTP
# ---------------------------------------------------------------------------


async def test_registry_register_get_list(
    client: AsyncClient, machine: tuple[MachineModel, str], auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/runtimes",
        json={
            "machine_id": str(machine[0].id),
            "provider_ref": "p7-provider",
            "model_ref": "p7-model",
            "capabilities": {"coding": True},
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    runtime = created.json()
    assert runtime["version"] == 1
    assert runtime["status"] == "active"
    assert runtime["owner_user_id"] == str(machine[0].owner_user_id)

    get = await client.get(f"/api/v1/runtimes/{runtime['id']}", headers=auth_headers)
    assert get.status_code == 200
    assert get.json()["id"] == runtime["id"]

    listed = await client.get("/api/v1/runtimes", headers=auth_headers)
    assert listed.status_code == 200
    assert runtime["id"] in [r["id"] for r in listed.json()]


async def test_registry_isolation_and_machine_gates(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
    other_auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/runtimes",
        json={"provider_ref": "p7", "model_ref": "m7"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    runtime_id = created.json()["id"]

    assert (
        await client.get(f"/api/v1/runtimes/{runtime_id}", headers=other_auth_headers)
    ).status_code == 404
    others = await client.get("/api/v1/runtimes", headers=other_auth_headers)
    assert runtime_id not in [r["id"] for r in others.json()]

    foreign_machine = await client.post(
        "/api/v1/runtimes",
        json={"machine_id": str(other_machine[0].id), "model_ref": "m7"},
        headers=auth_headers,
    )
    assert foreign_machine.status_code == 403
    unknown_machine = await client.post(
        "/api/v1/runtimes",
        json={"machine_id": str(uuid.uuid4()), "model_ref": "m7"},
        headers=auth_headers,
    )
    assert unknown_machine.status_code == 404
    assert (await client.get("/api/v1/runtimes")).status_code == 401
    assert (
        await client.post(
            "/api/v1/runtimes", json={"model_ref": "m7"}, headers=readonly_auth_headers
        )
    ).status_code == 403


async def test_registry_open_refs_and_secrets(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    future = await client.post(
        "/api/v1/runtimes",
        json={
            "harness_ref": "harness-from-2030",
            "provider_ref": "future-provider",
            "model_ref": "unreleased-model-xyz",
        },
        headers=auth_headers,
    )
    assert future.status_code == 201, future.text

    anchorless = await client.post("/api/v1/runtimes", json={}, headers=auth_headers)
    assert anchorless.status_code == 422

    secret = await client.post(
        "/api/v1/runtimes",
        json={"model_ref": "m7", "runtime_metadata": {"api_key": "x"}},
        headers=auth_headers,
    )
    assert secret.status_code == 422


async def test_registry_update_versioning_and_idempotency(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/runtimes",
        json={"provider_ref": "p7", "model_ref": "m7"},
        headers=auth_headers,
    )
    runtime = created.json()

    stale = await client.patch(
        f"/api/v1/runtimes/{runtime['id']}",
        json={"update": {"model_ref": "m8"}, "expected_version": 999},
        headers=auth_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["error_code"] == "version_conflict"
    assert stale.json()["detail"]["server_version"] == 1

    headers = {**auth_headers, "Idempotency-Key": f"p7-upd-{runtime['id']}"}
    updated = await client.patch(
        f"/api/v1/runtimes/{runtime['id']}",
        json={"update": {"model_ref": "m8"}, "expected_version": 1},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["model_ref"] == "m8"
    assert updated.json()["version"] == 2

    replay = await client.patch(
        f"/api/v1/runtimes/{runtime['id']}",
        json={"update": {"model_ref": "m8"}, "expected_version": 1},
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["version"] == 2

    mismatch = await client.patch(
        f"/api/v1/runtimes/{runtime['id']}",
        json={"update": {"model_ref": "m9"}, "expected_version": 2},
        headers=headers,
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"


async def test_registry_revoke_lifecycle(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    created = await client.post("/api/v1/runtimes", json={"model_ref": "m7"}, headers=auth_headers)
    runtime_id = created.json()["id"]

    assert (
        await client.post(f"/api/v1/runtimes/{runtime_id}/revoke", headers=other_auth_headers)
    ).status_code == 404

    revoked = await client.post(f"/api/v1/runtimes/{runtime_id}/revoke", headers=auth_headers)
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    again = await client.post(f"/api/v1/runtimes/{runtime_id}/revoke", headers=auth_headers)
    assert again.status_code == 200
    assert again.json()["status"] == "revoked"

    default_list = await client.get("/api/v1/runtimes", headers=auth_headers)
    assert runtime_id not in [r["id"] for r in default_list.json()]
    with_revoked = await client.get(
        "/api/v1/runtimes", params={"include_revoked": True}, headers=auth_headers
    )
    assert runtime_id in [r["id"] for r in with_revoked.json()]


async def test_registry_register_idempotency_p0(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = {"provider_ref": "p7idem", "model_ref": "m7"}
    headers = {**auth_headers, "Idempotency-Key": f"p7-reg-{uuid.uuid4().hex}"}
    first = await client.post("/api/v1/runtimes", json=body, headers=headers)
    assert first.status_code == 201
    replay = await client.post("/api/v1/runtimes", json=body, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    conflict = await client.post(
        "/api/v1/runtimes", json={"provider_ref": "other", "model_ref": "m7"}, headers=headers
    )
    assert conflict.status_code == 409


# ---------------------------------------------------------------------------
# Resolution HTTP
# ---------------------------------------------------------------------------


async def test_resolution_happy_path_provenance(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _gate_world(db_session, mine, "p7-a", "p7-m", {"coding": True})
    await bindings_service.create_binding(
        db_session,
        mine,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key="p7-a",
            target=RuntimeTarget(
                machine_id=machine[0].id,
                capabilities=RuntimeCapabilities(coding=True),
            ),
        ),
    )

    response = await client.post(
        "/api/v1/resolutions",
        json={"stable_key": "p7-a", "project_id": str(project.id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    resolved = response.json()
    assert resolved["agent"]["stable_key"] == "p7-a"
    assert resolved["agent"]["version"] == 1
    assert resolved["model_profile"]["stable_key"] == "p7-m"
    assert resolved["requirements"]["coding"] is True
    assert resolved["runtime"]["compatible"] is True
    assert resolved["runtime"]["level"] == "user"
    assert resolved["runtime"]["matched_stable_key"] == "p7-a"
    assert resolved["runtime"]["provenance"]["binding_level"] == "user"
    assert resolved["runtime"]["provenance"]["source"] == "runtime_binding"


async def test_resolution_incompatible_has_no_fallback(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
) -> None:
    mine = await _principal(db_session, machine)
    await _gate_world(db_session, mine, "p7-bad", "p7-badm", {"coding": True})
    await bindings_service.create_binding(
        db_session,
        mine,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key="p7-bad",
            target=RuntimeTarget(
                model_ref="weak-model",
                capabilities=RuntimeCapabilities(coding=False),
            ),
        ),
    )

    response = await client.post(
        "/api/v1/resolutions", json={"stable_key": "p7-bad"}, headers=auth_headers
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "runtime_incompatible"
    assert detail["matched_stable_key"] == "p7-bad"
    assert detail["unsatisfied"] != []


async def test_resolution_not_found_and_ownership(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    assert (
        await client.post("/api/v1/resolutions", json={"stable_key": "nope"})
    ).status_code == 401

    missing = await client.post(
        "/api/v1/resolutions", json={"stable_key": "no-such-agent"}, headers=auth_headers
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["error_code"] == "definition_not_found"

    mine = await _principal(db_session, machine)
    await _create(db_session, mine, AGENT, "p7-private", _agent_content(), scope=LibraryScope.USER)
    masked = await client.post(
        "/api/v1/resolutions", json={"stable_key": "p7-private"}, headers=other_auth_headers
    )
    assert masked.status_code == 404

    invalid = await client.post("/api/v1/resolutions", json={}, headers=auth_headers)
    assert invalid.status_code == 422


async def test_resolution_session_override_ephemeral(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
) -> None:
    mine = await _principal(db_session, machine)
    await _gate_world(db_session, mine, "p7-ephem", "p7-ephemm", {"coding": True})
    before = await bindings_service.list_bindings(db_session, mine)

    response = await client.post(
        "/api/v1/resolutions",
        json={
            "stable_key": "p7-ephem",
            "session_overrides": [
                {
                    "target_kind": "agent_definition",
                    "target_stable_key": "p7-ephem",
                    "target": {
                        "machine_id": str(machine[0].id),
                        "capabilities": {"coding": True},
                    },
                }
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    resolved = response.json()
    assert resolved["runtime"]["level"] == "session"
    assert resolved["runtime"]["provenance"]["source"] == "session_override"
    assert resolved["runtime"]["provenance"]["binding_level"] == "session"

    after = await bindings_service.list_bindings(db_session, mine)
    assert len(after) == len(before)

    duplicate = await client.post(
        "/api/v1/resolutions",
        json={
            "stable_key": "p7-ephem",
            "session_overrides": [
                {
                    "target_kind": "agent_definition",
                    "target_stable_key": "p7-ephem",
                    "target": {"model_ref": "m1"},
                },
                {
                    "target_kind": "agent_definition",
                    "target_stable_key": "p7-ephem",
                    "target": {"model_ref": "m2"},
                },
            ],
        },
        headers=auth_headers,
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"]["error_code"] == "invalid_resolution_input"


async def test_resolution_revoked_runtime_binding_falls_through(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
) -> None:
    from studio_api.services import runtime_registry as registry_service
    from studio_contracts.runtime import RuntimeRegistrationCreate

    mine = await _principal(db_session, machine)
    await _gate_world(db_session, mine, "p7-rev", "p7-revm", {"coding": True})
    runtime = await registry_service.register_runtime(
        db_session, mine, RuntimeRegistrationCreate(model_ref="doomed")
    )
    await registry_service.revoke_runtime(
        db_session,
        mine,
        (await registry_service.get_runtime(db_session, mine, runtime.id)),  # type: ignore[arg-type]
    )
    await bindings_service.create_binding(
        db_session,
        mine,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key="p7-rev",
            target=RuntimeTarget(runtime_id=runtime.id),
        ),
    )

    response = await client.post(
        "/api/v1/resolutions", json={"stable_key": "p7-rev"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["runtime"] is None


# ---------------------------------------------------------------------------
# OpenAPI / surface gates
# ---------------------------------------------------------------------------


async def test_openapi_canonical_surface(client: AsyncClient) -> None:
    doc = (await client.get("/openapi.json")).json()
    paths: dict[str, Any] = doc["paths"]
    for expected in (
        "/api/v1/runtime-bindings",
        "/api/v1/runtime-bindings/{binding_id}",
        "/api/v1/runtimes",
        "/api/v1/runtimes/{runtime_id}",
        "/api/v1/runtimes/{runtime_id}/revoke",
        "/api/v1/resolutions",
    ):
        assert expected in paths, expected
    assert "post" in paths["/api/v1/resolutions"]

    vendor = [p for p in paths if any(v in p for v in ("ollama", "openai", "anthropic"))]
    assert vendor == []
    aliases = [p for p in paths if p.rstrip("/").endswith("/resolve") or p == "/api/v1/resolve"]
    assert aliases == []

    def _params(method: dict[str, Any]) -> list[dict[str, Any]]:
        return method.get("parameters", [])

    for path, operation in (
        ("/api/v1/runtime-bindings", "post"),
        ("/api/v1/runtimes", "post"),
        ("/api/v1/runtimes/{runtime_id}", "patch"),
    ):
        names = [p["name"] for p in _params(paths[path][operation])]
        assert "Idempotency-Key" in names, (path, operation)

    create_schema = doc["components"]["schemas"]["RuntimeRegistrationCreate"]
    for ref in ("provider_ref", "harness_ref", "model_ref"):
        prop = create_schema["properties"][ref]
        assert "enum" not in prop, ref
    assert "version" in doc["components"]["schemas"]["RuntimeRegistration"]["properties"]

    assert "AgentResolutionRequest" in doc["components"]["schemas"]
    assert "ResolvedAgentDefinition" in doc["components"]["schemas"]

    tags = {t["name"] for t in doc["tags"]}
    assert {"runtime-bindings", "runtimes", "resolutions"} <= tags
