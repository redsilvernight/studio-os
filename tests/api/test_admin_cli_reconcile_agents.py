"""`studio-admin reconcile-agents` (DEC-0237): dry-run by default, explicit,
and reversible — a former identity only gains a pointer, never a merge."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api import admin_cli
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.services import provisioning as provisioning_service


class _SessionContext:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _bind_session(monkeypatch: pytest.MonkeyPatch, session: AsyncSession) -> None:
    monkeypatch.setattr(admin_cli, "get_session_factory", lambda: lambda: _SessionContext(session))


async def _identities(
    db_session: AsyncSession,
) -> tuple[MachineModel, AgentModel, AgentModel]:
    owner = await provisioning_service.create_user(
        db_session, "Owner", f"{uuid.uuid4()}@example.test", "developer"
    )
    machine, _ = await provisioning_service.create_machine(db_session, owner.id, "poste")
    canonical = AgentModel(
        owner_user_id=owner.id,
        machine_id=machine.id,
        display_name="gpt-6.1-sol",
        agent_kind="model",
        harness="codex",
        provider="openai",
        model="gpt-6.1-sol",
        stable_key=f"canonical-model-v1:{uuid.uuid4().hex}",
    )
    legacy = AgentModel(
        machine_id=machine.id,
        display_name="gpt-6.1-sol",
        agent_kind="model",
        harness="codex-cli",
        provider="OpenAI",
        model="gpt-6.1-sol",
        stable_key="agents-ensure-codex:openai/gpt-6.1-sol",
    )
    db_session.add_all([canonical, legacy])
    await db_session.commit()
    await db_session.refresh(canonical)
    await db_session.refresh(legacy)
    return machine, canonical, legacy


async def test_dry_run_reports_without_writing(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _bind_session(monkeypatch, db_session)
    _, canonical, legacy = await _identities(db_session)

    await admin_cli._reconcile_agents(None, None, False)

    await db_session.refresh(legacy)
    assert legacy.superseded_by_agent_id is None
    output = capsys.readouterr().out
    assert "1 link(s) would be created" in output
    assert str(canonical.id) in output


async def test_apply_links_then_revert_restores_the_former_state(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _bind_session(monkeypatch, db_session)
    _, canonical, legacy = await _identities(db_session)
    before = (legacy.machine_id, legacy.harness, legacy.provider, legacy.stable_key)

    await admin_cli._reconcile_agents(None, None, True)

    await db_session.refresh(legacy)
    assert legacy.superseded_by_agent_id == canonical.id
    assert (legacy.machine_id, legacy.harness, legacy.provider, legacy.stable_key) == before
    assert "1 link(s) committed" in capsys.readouterr().out

    await admin_cli._reconcile_agents(None, str(legacy.id), True)

    await db_session.refresh(legacy)
    assert legacy.superseded_by_agent_id is None
    assert (legacy.machine_id, legacy.harness, legacy.provider, legacy.stable_key) == before
    assert "link to" in capsys.readouterr().out


async def test_revert_dry_run_keeps_the_link(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _bind_session(monkeypatch, db_session)
    _, canonical, legacy = await _identities(db_session)
    await admin_cli._reconcile_agents(None, None, True)
    capsys.readouterr()

    await admin_cli._reconcile_agents(None, str(legacy.id), False)

    await db_session.refresh(legacy)
    assert legacy.superseded_by_agent_id == canonical.id
    assert "would clear link" in capsys.readouterr().out
