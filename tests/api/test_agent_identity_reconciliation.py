"""Explicit, reversible reconciliation of former agent identities (DEC-0237).

A former identity keeps its machine, metadata, stable key and history: the
link is a single pointer, so it can be cleared and re-applied without ever
rewriting provenance or deleting a row. Needs the real Postgres test DB.
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel

PATH = "/api/v1/agents/resolve-identity"


def payload(**overrides: Any) -> dict[str, Any]:
    return {
        "harness": "codex-desktop",
        "provider": "openai",
        "effective_model": "gpt-6.1-sol",
        "selection_alias": "sol",
        **overrides,
    }


async def _legacy(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    *,
    harness: str = "codex-cli",
    provider: str = " OpenAI ",
    model: str = "gpt-6.1-sol",
    stable_key: str = "agents-ensure-codex:openai/gpt-6.1-sol",
) -> AgentModel:
    row = AgentModel(
        machine_id=machine[0].id,
        display_name=model,
        agent_kind="model",
        harness=harness,
        provider=provider,
        model=model,
        stable_key=stable_key,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _canonical(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> str:
    resolved = await client.post(PATH, headers=headers, json=payload(**overrides))
    assert resolved.status_code == 201, resolved.text
    return resolved.json()["agent"]["id"]


async def test_former_identity_is_linked_without_rewriting_provenance(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    canonical_id = await _canonical(client, auth_headers)
    legacy = await _legacy(db_session, machine)
    before = (
        legacy.machine_id,
        legacy.display_name,
        legacy.harness,
        legacy.provider,
        legacy.model,
        legacy.stable_key,
    )

    linked = await client.post(
        f"/api/v1/agents/{legacy.id}/supersede",
        headers=auth_headers,
        json={"canonical_agent_id": canonical_id},
    )

    assert linked.status_code == 200, linked.text
    assert linked.json()["superseded_by_agent_id"] == canonical_id
    await db_session.refresh(legacy)
    assert (
        legacy.machine_id,
        legacy.display_name,
        legacy.harness,
        legacy.provider,
        legacy.model,
        legacy.stable_key,
    ) == before
    assert legacy.owner_user_id is None
    assert legacy.superseded_by_agent_id is not None

    again = await client.post(
        f"/api/v1/agents/{legacy.id}/supersede",
        headers=auth_headers,
        json={"canonical_agent_id": canonical_id},
    )
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["error_code"] == "already_superseded"
    assert again.json()["detail"]["superseded_by_agent_id"] == canonical_id


async def test_link_is_hidden_unless_requested(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    canonical_id = await _canonical(client, auth_headers)
    legacy = await _legacy(db_session, machine)
    linked = await client.post(
        f"/api/v1/agents/{legacy.id}/supersede",
        headers=auth_headers,
        json={"canonical_agent_id": canonical_id},
    )
    assert linked.status_code == 200, linked.text

    legacy_shape = await client.get("/api/v1/agents", headers=auth_headers)
    assert all("superseded_by_agent_id" not in row for row in legacy_shape.json())
    extended = await client.get(
        "/api/v1/agents",
        headers=auth_headers,
        params={"include_identity_link": True},
    )
    row = next(item for item in extended.json() if item["id"] == str(legacy.id))
    assert row["superseded_by_agent_id"] == canonical_id
    assert "owner_user_id" not in row


async def test_self_link_and_non_canonical_target_are_refused(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    canonical_id = await _canonical(client, auth_headers)
    legacy = await _legacy(db_session, machine)
    other_legacy = await _legacy(
        db_session,
        machine,
        harness="claude-code",
        provider="anthropic",
        model="claude-opus-5-5",
        stable_key="agents-ensure-claude:anthropic/claude-opus-5-5",
    )

    same = await client.post(
        f"/api/v1/agents/{canonical_id}/supersede",
        headers=auth_headers,
        json={"canonical_agent_id": canonical_id},
    )
    assert same.status_code == 409, same.text
    assert same.json()["detail"]["error_code"] == "invalid_identity_link"

    towards_legacy = await client.post(
        f"/api/v1/agents/{legacy.id}/supersede",
        headers=auth_headers,
        json={"canonical_agent_id": str(other_legacy.id)},
    )
    assert towards_legacy.status_code == 409, towards_legacy.text
    assert towards_legacy.json()["detail"]["error_code"] == "invalid_identity_link"


async def test_another_users_canonical_identity_requires_admin(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    foreign_canonical = await _canonical(client, other_auth_headers, effective_model="gpt-6-astra")
    legacy = await _legacy(db_session, machine)

    refused = await client.post(
        f"/api/v1/agents/{legacy.id}/supersede",
        headers=auth_headers,
        json={"canonical_agent_id": foreign_canonical},
    )
    assert refused.status_code == 403, refused.text

    allowed = await client.post(
        f"/api/v1/agents/{legacy.id}/supersede",
        headers=admin_auth_headers,
        json={"canonical_agent_id": foreign_canonical},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["superseded_by_agent_id"] == foreign_canonical


async def test_readonly_cannot_link(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    readonly_machine: tuple[MachineModel, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    canonical_id = await _canonical(client, auth_headers)
    legacy = await _legacy(db_session, readonly_machine)

    result = await client.post(
        f"/api/v1/agents/{legacy.id}/supersede",
        headers=readonly_auth_headers,
        json={"canonical_agent_id": canonical_id},
    )
    assert result.status_code == 403, result.text


async def test_reconciliation_plan_pairs_legacy_rows_with_their_canonical_identity(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    canonical_id = await _canonical(client, auth_headers)
    legacy = await _legacy(db_session, machine)
    unmatched = await _legacy(
        db_session,
        machine,
        harness="opencode",
        provider="opencode-go",
        model="never-resolved",
        stable_key="agents-ensure-opencode:opencode-go/never-resolved",
    )

    from studio_api.services import agents as agents_service

    plan = await agents_service.plan_identity_reconciliation(db_session)
    linked = {str(link.legacy_agent_id): str(link.canonical_agent_id) for link in plan.links}
    assert linked[str(legacy.id)] == canonical_id
    assert str(unmatched.id) not in linked
    assert plan.unmatched_legacy >= 1

    written = await agents_service.apply_identity_reconciliation(db_session, plan)
    await db_session.commit()
    assert written >= 1
    await db_session.refresh(legacy)
    assert str(legacy.superseded_by_agent_id) == canonical_id
