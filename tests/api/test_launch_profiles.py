"""Work profiles on task launches (DEC-0198) — the profile a launch pins.

Covers the server half of the contract: `profile_key` on
`TaskLaunchCreate`, the `profile` pin on `TaskLaunch` (absent when no profile
was asked for), and the three refusals that keep a profile nobody can
enforce from being stored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.library import LibraryResourceModel
from studio_api.db.models.machine import MachineModel
from studio_api.services import library as library_service
from studio_api.services import resolution as resolution_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.library import (
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersionCreate,
)
from studio_contracts.profiles import (
    LaunchProfilePin,
    pin_profile,
    profile_elements,
    reference_work_profile,
)

AGENT_KEY = "launch-profiled-agent"

AGENT_CONTENT = {
    "content_schema": "studio.library.agent_definition/v1",
    "summary": "Fictional helper profiled by a launch.",
    "intended_use": "Exercise the launch profile pin.",
}


async def _principal(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> Principal:
    model, _ = machine
    return await load_principal(db_session, model)


async def _agent_definition(
    db_session: AsyncSession, principal: Principal, key: str = AGENT_KEY
) -> LibraryResourceModel:
    resource, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=LibraryKind.AGENT_DEFINITION,
            stable_key=key,
            scope=LibraryScope.STUDIO,
            project_id=None,
            title=f"{key} title",
            description=None,
            content=dict(AGENT_CONTENT),
            dependencies=[],
        ),
    )
    await db_session.refresh(resource)
    await library_service.activate_resource_version(db_session, principal, resource, 1, 1)
    return resource


async def _next_version(
    db_session: AsyncSession, principal: Principal, resource: LibraryResourceModel
) -> None:
    """A second version of the same agent definition, activated: a Library
    version bump the pinned element versions must follow."""
    await library_service.create_resource_version(
        db_session,
        principal,
        resource,
        LibraryVersionCreate(title="v2", content=dict(AGENT_CONTENT)),
    )
    await db_session.refresh(resource)
    await library_service.activate_resource_version(
        db_session, principal, resource, 2, resource.version
    )


async def _project_task(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    project = await client.post(
        "/api/v1/projects",
        json={"slug": f"pf-{uuid.uuid4().hex[:8]}", "name": "Profile"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    task = await client.post(
        "/api/v1/tasks", json={"project_id": project_id, "title": "t"}, headers=headers
    )
    assert task.status_code == 201, task.text
    return project_id, task.json()["id"]


def _caps(project_id: str, **overrides: Any) -> dict[str, Any]:
    caps: dict[str, Any] = {
        "harnesses": [{"harness_id": "claude-code", "version": "2.1.0"}],
        "project_ids": [project_id],
        "accepts_launches": True,
        "running_launches": 0,
        "max_launches": 2,
    }
    caps.update(overrides)
    return caps


async def _heartbeat(
    client: AsyncClient, headers: dict[str, str], machine_id: str, capabilities: dict[str, Any]
) -> None:
    response = await client.post(
        "/api/v1/heartbeats",
        headers=headers,
        json={
            "machine_id": machine_id,
            "client_timestamp": datetime.now(UTC).isoformat(),
            "capabilities": capabilities,
        },
    )
    assert response.status_code == 200, response.text


async def _target(
    client: AsyncClient,
    headers: dict[str, str],
    machine: tuple[MachineModel, str],
    **caps_overrides: Any,
) -> tuple[str, str, str]:
    model, _ = machine
    project_id, task_id = await _project_task(client, headers)
    await _heartbeat(client, headers, str(model.id), _caps(project_id, **caps_overrides))
    return project_id, task_id, str(model.id)


async def _launch(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    task_id: str,
    machine_id: str,
    **overrides: Any,
) -> Any:
    body: dict[str, Any] = {
        "task_id": task_id,
        "machine_id": machine_id,
        "harness_id": "claude-code",
    }
    body.update(overrides)
    return await client.post(
        f"/api/v1/projects/{project_id}/task-launches", json=body, headers=headers
    )


async def _expected_pin(
    db_session: AsyncSession,
    principal: Principal,
    project_id: str,
    profile_key: str,
    agent_key: str,
) -> dict[str, Any]:
    """The pin the daemon recomputes: the reference profile pinned against
    the element versions the server's own resolver reads right now."""
    profile = reference_work_profile(profile_key, agent_key)
    definition = await resolution_service.resolve_full(
        db_session,
        principal,
        LibraryKind.AGENT_DEFINITION,
        agent_key,
        uuid.UUID(project_id),
    )
    pin: LaunchProfilePin = pin_profile(profile, profile_elements(definition))
    return pin.model_dump(mode="json")


async def test_profiled_launch_pins_the_reference_profile(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    principal = await _principal(db_session, machine)
    await _agent_definition(db_session, principal)
    project_id, task_id, machine_id = await _target(
        client, auth_headers, machine, launch_profiles=True
    )

    response = await _launch(
        client,
        auth_headers,
        project_id,
        task_id,
        machine_id,
        agent_stable_key=AGENT_KEY,
        profile_key="coding",
    )
    assert response.status_code == 201, response.text
    assert response.json()["profile"] == await _expected_pin(
        db_session, principal, project_id, "coding", AGENT_KEY
    )


async def test_read_only_profile_pins_its_own_key(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    principal = await _principal(db_session, machine)
    await _agent_definition(db_session, principal)
    project_id, task_id, machine_id = await _target(
        client, auth_headers, machine, launch_profiles=True
    )

    response = await _launch(
        client,
        auth_headers,
        project_id,
        task_id,
        machine_id,
        agent_stable_key=AGENT_KEY,
        profile_key="architecture-read-only",
    )
    assert response.status_code == 201, response.text
    assert response.json()["profile"]["stable_key"] == "architecture-read-only"
    assert response.json()["profile"] == await _expected_pin(
        db_session, principal, project_id, "architecture-read-only", AGENT_KEY
    )


async def test_profile_key_without_agent_is_422(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _target(
        client, auth_headers, machine, launch_profiles=True
    )
    response = await _launch(
        client, auth_headers, project_id, task_id, machine_id, profile_key="coding"
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error_code"] == "profile_requires_agent"


async def test_unknown_profile_key_is_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    principal = await _principal(db_session, machine)
    await _agent_definition(db_session, principal)
    project_id, task_id, machine_id = await _target(
        client, auth_headers, machine, launch_profiles=True
    )
    response = await _launch(
        client,
        auth_headers,
        project_id,
        task_id,
        machine_id,
        agent_stable_key=AGENT_KEY,
        profile_key="not-a-reference-profile",
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {
        "error_code": "unknown_profile",
        "profile_key": "not-a-reference-profile",
    }


@pytest.mark.parametrize("reported", [None, False])
async def test_machine_without_launch_profiles_is_409(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    reported: bool | None,
) -> None:
    principal = await _principal(db_session, machine)
    await _agent_definition(db_session, principal)
    overrides = {} if reported is None else {"launch_profiles": reported}
    project_id, task_id, machine_id = await _target(client, auth_headers, machine, **overrides)

    refused = await _launch(
        client,
        auth_headers,
        project_id,
        task_id,
        machine_id,
        agent_stable_key=AGENT_KEY,
        profile_key="coding",
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["error_code"] == "profile_unsupported_by_machine"

    unprofiled = await _launch(
        client, auth_headers, project_id, task_id, machine_id, agent_stable_key=AGENT_KEY
    )
    assert unprofiled.status_code == 201, unprofiled.text
    assert "profile" not in unprofiled.json()


async def test_unprofiled_launch_omits_the_profile_key(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _target(client, auth_headers, machine)
    response = await _launch(client, auth_headers, project_id, task_id, machine_id)
    assert response.status_code == 201, response.text
    assert "profile" not in response.json()

    pull = await client.get(
        f"/api/v1/machines/{machine_id}/task-launches/pending", headers=auth_headers
    )
    assert pull.status_code == 200, pull.text
    assert all("profile" not in item for item in pull.json()["items"])


async def test_pull_carries_the_profile_pin(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    principal = await _principal(db_session, machine)
    await _agent_definition(db_session, principal)
    project_id, task_id, machine_id = await _target(
        client, auth_headers, machine, launch_profiles=True
    )
    created = await _launch(
        client,
        auth_headers,
        project_id,
        task_id,
        machine_id,
        agent_stable_key=AGENT_KEY,
        profile_key="coding",
    )
    assert created.status_code == 201, created.text

    pull = await client.get(
        f"/api/v1/machines/{machine_id}/task-launches/pending", headers=auth_headers
    )
    assert pull.status_code == 200, pull.text
    item = next(i for i in pull.json()["items"] if i["id"] == created.json()["id"])
    assert item["profile"] == await _expected_pin(
        db_session, principal, project_id, "coding", AGENT_KEY
    )


async def test_pull_withholds_a_profiled_launch_once_the_machine_stops_advertising(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    principal = await _principal(db_session, machine)
    await _agent_definition(db_session, principal)
    project_id, task_id, machine_id = await _target(
        client, auth_headers, machine, launch_profiles=True
    )
    profiled = await _launch(
        client,
        auth_headers,
        project_id,
        task_id,
        machine_id,
        agent_stable_key=AGENT_KEY,
        profile_key="coding",
    )
    assert profiled.status_code == 201, profiled.text
    plain = await _launch(client, auth_headers, project_id, task_id, machine_id)
    assert plain.status_code == 201, plain.text

    await _heartbeat(client, auth_headers, machine_id, _caps(project_id))
    pull = await client.get(
        f"/api/v1/machines/{machine_id}/task-launches/pending", headers=auth_headers
    )
    assert pull.status_code == 200, pull.text
    ids = {item["id"] for item in pull.json()["items"]}
    assert plain.json()["id"] in ids
    assert profiled.json()["id"] not in ids


async def test_retry_inherits_the_profile_and_recomputes_its_pin(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    principal = await _principal(db_session, machine)
    agent = await _agent_definition(db_session, principal)
    project_id, task_id, machine_id = await _target(
        client, auth_headers, machine, launch_profiles=True
    )
    created = (
        await _launch(
            client,
            auth_headers,
            project_id,
            task_id,
            machine_id,
            agent_stable_key=AGENT_KEY,
            profile_key="coding",
        )
    ).json()
    first_pin = created["profile"]

    await _next_version(db_session, principal, agent)
    cancelled = await client.post(
        f"/api/v1/task-launches/{created['id']}/cancel",
        json={"expected_version": created["version"]},
        headers=auth_headers,
    )
    assert cancelled.status_code == 200, cancelled.text

    retried = await client.post(
        f"/api/v1/task-launches/{created['id']}/retry", json={}, headers=auth_headers
    )
    assert retried.status_code == 201, retried.text
    body = retried.json()
    assert body["attempt"] == 2
    assert body["profile"]["stable_key"] == "coding"
    assert body["profile"] == await _expected_pin(
        db_session, principal, project_id, "coding", AGENT_KEY
    )
    assert body["profile"]["digest"] != first_pin["digest"]


async def test_retry_on_a_machine_that_dropped_profiles_is_409(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    """A profile the target machine can no longer enforce is not retried
    behind the machine's back: the retry re-checks the aptitude a creation
    would."""
    principal = await _principal(db_session, machine)
    await _agent_definition(db_session, principal)
    project_id, task_id, machine_id = await _target(
        client, auth_headers, machine, launch_profiles=True
    )
    created = (
        await _launch(
            client,
            auth_headers,
            project_id,
            task_id,
            machine_id,
            agent_stable_key=AGENT_KEY,
            profile_key="coding",
        )
    ).json()
    cancelled = await client.post(
        f"/api/v1/task-launches/{created['id']}/cancel",
        json={"expected_version": created["version"]},
        headers=auth_headers,
    )
    assert cancelled.status_code == 200, cancelled.text

    model, _ = machine
    await _heartbeat(client, auth_headers, str(model.id), _caps(project_id))
    retried = await client.post(
        f"/api/v1/task-launches/{created['id']}/retry", json={}, headers=auth_headers
    )
    assert retried.status_code == 409, retried.text
    assert retried.json()["detail"]["error_code"] == "profile_unsupported_by_machine"


async def test_heartbeat_stores_and_echoes_launch_profiles(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    """`launch_profiles` is stored with the rest of the capabilities and read
    back: a machine that stops reporting it stops accepting profiled
    launches (a missing report is never a `true`)."""
    model, _ = machine
    project_id, _ = await _project_task(client, auth_headers)

    reported = await client.post(
        "/api/v1/heartbeats",
        headers=auth_headers,
        json={
            "machine_id": str(model.id),
            "client_timestamp": datetime.now(UTC).isoformat(),
            "capabilities": _caps(project_id, launch_profiles=True),
        },
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["capabilities"]["launch_profiles"] is True

    stored = await db_session.get(MachineModel, model.id)
    assert stored is not None
    assert stored.capabilities["launch_profiles"] is True

    silent = await client.post(
        "/api/v1/heartbeats",
        headers=auth_headers,
        json={
            "machine_id": str(model.id),
            "client_timestamp": datetime.now(UTC).isoformat(),
            "capabilities": _caps(project_id, launch_profiles=False),
        },
    )
    assert silent.status_code == 200, silent.text
    assert silent.json()["capabilities"]["launch_profiles"] is False
    await db_session.refresh(stored)
    assert stored.capabilities["launch_profiles"] is False
