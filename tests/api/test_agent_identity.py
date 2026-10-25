from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import provisioning

PATH = "/api/v1/agents/resolve-identity"


def payload(**overrides: Any) -> dict[str, Any]:
    return {
        "harness": "codex-desktop",
        "provider": "openai",
        "effective_model": "gpt-6.1-sol",
        "selection_alias": "sol",
        **overrides,
    }


async def test_identity_stays_stable_across_interfaces_aliases_and_models(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    first = await client.post(
        PATH,
        headers=auth_headers,
        json=payload(provider=" OpenAI ", effective_model=" gpt-6.1-sol "),
    )
    assert first.status_code == 201, first.text
    identity = first.json()["agent"]
    second = await client.post(
        PATH,
        headers=auth_headers,
        json=payload(harness="codex-cli", selection_alias="latest"),
    )
    assert second.status_code == 200, second.text
    assert second.json()["agent"]["id"] == identity["id"]
    assert second.json()["logical_harness"] == "codex"
    assert second.json()["selection_alias"] == "latest"
    other_model = await client.post(
        PATH,
        headers=auth_headers,
        json=payload(effective_model="gpt-6-astra"),
    )
    other_harness = await client.post(
        PATH,
        headers=auth_headers,
        json=payload(harness="opencode"),
    )
    assert (
        len(
            {identity["id"], other_model.json()["agent"]["id"], other_harness.json()["agent"]["id"]}
        )
        == 3
    )
    count = (await db_session.execute(select(func.count()).select_from(AgentModel))).scalar_one()
    assert count == 3


async def test_unknown_model_or_provider_creates_no_identity(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    for missing in ({"effective_model": None}, {"effective_model": "default"}, {"provider": None}):
        result = await client.post(PATH, headers=auth_headers, json=payload(**missing))
        assert result.status_code == 200, result.text
        assert result.json()["state"] == "unknown"
        assert result.json()["agent"] is None
        assert result.json()["created"] is False
    assert (
        await db_session.execute(select(func.count()).select_from(AgentModel))
    ).scalar_one() == 0


async def test_same_user_reuses_identity_on_another_machine_and_keeps_execution_machine(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    first = await client.post(PATH, headers=auth_headers, json=payload())
    identity = first.json()["agent"]
    second_machine, token = await provisioning.create_machine(
        db_session,
        machine[0].owner_user_id,
        "second-authorized-machine",
    )
    second_headers = {"Authorization": f"Bearer {token}"}
    reused = await client.post(PATH, headers=second_headers, json=payload())
    assert reused.status_code == 200, reused.text
    assert reused.json()["agent"]["id"] == identity["id"]
    assert reused.json()["agent"]["machine_id"] == str(machine[0].id)
    task = await client.post(
        "/api/v1/tasks",
        headers=second_headers,
        json={"project_id": str(project.id), "title": "Durable identity work"},
    )
    started = await client.post(
        "/api/v1/start-work",
        headers=second_headers,
        json={
            "project_id": str(project.id),
            "task_id": task.json()["id"],
            "agent_id": identity["id"],
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["session"]["machine_id"] == str(second_machine.id)
    assert started.json()["session"]["agent_id"] == identity["id"]


async def test_accounts_are_separate_and_cannot_attribute_another_users_identity(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    first = await client.post(PATH, headers=auth_headers, json=payload())
    second = await client.post(PATH, headers=other_auth_headers, json=payload())
    assert first.json()["agent"]["id"] != second.json()["agent"]["id"]
    listing = await client.get("/api/v1/agents", headers=other_auth_headers)
    assert first.json()["agent"]["id"] not in [a["id"] for a in listing.json()]
    spoofed = await client.post(
        "/api/v1/start-work",
        headers=other_auth_headers,
        json={"project_id": str(project.id), "agent_id": first.json()["agent"]["id"]},
    )
    assert spoofed.status_code == 409, spoofed.text
    assert spoofed.json()["detail"]["error_code"] == "actor_not_owned"


async def test_readonly_cannot_create_identity(
    client: AsyncClient,
    readonly_auth_headers: dict[str, str],
) -> None:
    result = await client.post(PATH, headers=readonly_auth_headers, json=payload())
    assert result.status_code == 403, result.text


async def test_other_user_cannot_use_canonical_identity_in_a_direct_session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    first = await client.post(PATH, headers=auth_headers, json=payload())
    task = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Direct session identity"},
    )
    result = await client.post(
        "/api/v1/sessions",
        headers=other_auth_headers,
        json={
            "task_id": task.json()["id"],
            "machine_id": str(other_machine[0].id),
            "agent_id": first.json()["agent"]["id"],
        },
    )
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["error_code"] == "actor_not_owned"


async def test_resolution_preserves_legacy_identity_and_provenance(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    agent: AgentModel,
) -> None:
    old = (agent.id, agent.machine_id, agent.stable_key, agent.version)
    resolved = await client.post(PATH, headers=auth_headers, json=payload())
    assert resolved.status_code == 201, resolved.text
    await db_session.refresh(agent)
    assert (agent.id, agent.machine_id, agent.stable_key, agent.version) == old
    assert agent.owner_user_id is None
    assert resolved.json()["agent"]["id"] != str(agent.id)
