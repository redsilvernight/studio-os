from __future__ import annotations

import sys
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api import admin_cli
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.machine_launch_grant import MachineLaunchGrantModel
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


async def _two_machines(
    db_session: AsyncSession, same_owner: bool = True
) -> tuple[object, MachineModel, MachineModel]:
    owner = await provisioning_service.create_user(
        db_session, "Owner", f"{uuid.uuid4()}@example.test", "developer"
    )
    source, _ = await provisioning_service.create_machine(db_session, owner.id, "source")
    if same_owner:
        target, _ = await provisioning_service.create_machine(db_session, owner.id, "target")
    else:
        other = await provisioning_service.create_user(
            db_session, "Other", f"{uuid.uuid4()}@example.test", "developer"
        )
        target, _ = await provisioning_service.create_machine(db_session, other.id, "target")
    return owner, source, target


async def test_machine_fk_columns_discovered_from_catalog(db_session: AsyncSession) -> None:
    columns = set(await admin_cli._machine_fk_columns(db_session))

    assert ("agents", "machine_id") in columns
    assert ("events", "machine_id") in columns
    assert ("resource_claims", "claimed_by_machine_id") in columns
    assert ("machine_launch_grants", "machine_id") in columns
    assert ("refresh_tokens", "machine_id") in columns


async def test_merge_machines_dry_run_writes_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _bind_session(monkeypatch, db_session)
    owner, source, target = await _two_machines(db_session)
    source_id = source.id
    target_id = target.id
    target_hash = target.credential_hash
    assert target_hash != source.credential_hash
    agent = AgentModel(
        machine_id=source_id,
        display_name="agent",
        agent_kind="claude_code",
        stable_key=f"k-{uuid.uuid4()}",
    )
    db_session.add(agent)
    await db_session.flush()

    await admin_cli._merge_machines(str(source_id), str(target_id), apply=False)

    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "would be reassigned" in out
    await db_session.refresh(agent)
    assert agent.machine_id == source_id
    assert await provisioning_service.get_machine(db_session, source_id) is not None
    await db_session.refresh(target)
    assert target.credential_hash == target_hash


async def test_merge_machines_apply_moves_references_and_credential(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _bind_session(monkeypatch, db_session)
    owner, source, target = await _two_machines(db_session)
    source_hash = source.credential_hash
    assert target.credential_hash != source_hash
    agent = AgentModel(
        machine_id=source.id,
        display_name="agent",
        agent_kind="claude_code",
        stable_key=f"k-{uuid.uuid4()}",
    )
    grant = MachineLaunchGrantModel(
        machine_id=source.id, user_id=owner.id, granted_by_user_id=owner.id
    )
    db_session.add_all([agent, grant])
    await db_session.commit()

    await admin_cli._merge_machines(str(source.id), str(target.id), apply=True)

    out = capsys.readouterr().out
    assert "reassigned" in out
    assert "source machine deleted" in out
    await db_session.refresh(agent)
    assert agent.machine_id == target.id
    moved_grant = (
        await db_session.execute(
            select(MachineLaunchGrantModel).where(MachineLaunchGrantModel.user_id == owner.id)
        )
    ).scalar_one()
    assert moved_grant.machine_id == target.id
    assert await provisioning_service.get_machine(db_session, source.id) is None
    await db_session.refresh(target)
    assert target.credential_hash == source_hash
    assert target.version >= 2


async def test_merge_machines_is_atomic_on_unique_conflict(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)
    _owner, source, target = await _two_machines(db_session)
    source_id = source.id
    target_id = target.id
    stable_key = f"dup-{uuid.uuid4()}"
    db_session.add_all(
        [
            AgentModel(
                machine_id=source_id,
                display_name="source",
                agent_kind="claude_code",
                stable_key=stable_key,
            ),
            AgentModel(
                machine_id=target_id,
                display_name="target",
                agent_kind="claude_code",
                stable_key=stable_key,
            ),
        ]
    )
    await db_session.commit()

    with pytest.raises(SystemExit) as exc_info:
        await admin_cli._merge_machines(str(source_id), str(target_id), apply=True)

    assert exc_info.value.code == 1
    remaining = (
        (await db_session.execute(select(AgentModel).where(AgentModel.machine_id == source_id)))
        .scalars()
        .all()
    )
    assert len(remaining) == 1
    assert await provisioning_service.get_machine(db_session, source_id) is not None


async def test_merge_machines_refuses_identical_ids() -> None:
    machine_id = str(uuid.uuid4())
    with pytest.raises(SystemExit) as exc_info:
        await admin_cli._merge_machines(machine_id, machine_id, apply=True)
    assert exc_info.value.code == 2


async def test_merge_machines_refuses_unknown_machine(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)
    _owner, source, target = await _two_machines(db_session)

    with pytest.raises(SystemExit) as exc_info:
        await admin_cli._merge_machines(str(source.id), str(uuid.uuid4()), apply=True)

    assert exc_info.value.code == 1
    assert await provisioning_service.get_machine(db_session, source.id) is not None
    assert await provisioning_service.get_machine(db_session, target.id) is not None


async def test_merge_machines_refuses_different_owners(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)
    _owner, source, target = await _two_machines(db_session, same_owner=False)

    with pytest.raises(SystemExit) as exc_info:
        await admin_cli._merge_machines(str(source.id), str(target.id), apply=True)

    assert exc_info.value.code == 1
    assert await provisioning_service.get_machine(db_session, source.id) is not None


def test_main_dispatches_merge_machines_dry_run_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, bool]] = []

    async def fake_merge(source: str, target: str, apply: bool) -> None:
        calls.append((source, target, apply))

    monkeypatch.setattr(admin_cli, "_merge_machines", fake_merge)
    source = str(uuid.uuid4())
    target = str(uuid.uuid4())
    monkeypatch.setattr(
        sys,
        "argv",
        ["studio-admin", "merge-machines", "--from", source, "--into", target],
    )

    admin_cli.main()

    assert calls == [(source, target, False)]


def test_main_dispatches_merge_machines_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, bool]] = []

    async def fake_merge(source: str, target: str, apply: bool) -> None:
        calls.append((source, target, apply))

    monkeypatch.setattr(admin_cli, "_merge_machines", fake_merge)
    source = str(uuid.uuid4())
    target = str(uuid.uuid4())
    monkeypatch.setattr(
        sys,
        "argv",
        ["studio-admin", "merge-machines", "--from", source, "--into", target, "--apply"],
    )

    admin_cli.main()

    assert calls == [(source, target, True)]
