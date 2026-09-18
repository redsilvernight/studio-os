from __future__ import annotations

import io
import sys
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api import admin_cli
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


async def test_cli_create_user(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_session(monkeypatch, db_session)
    email = f"{uuid.uuid4()}@example.test"

    await admin_cli._create_user("Ada Lovelace", email, "developer")

    user = await provisioning_service.get_user_by_email(db_session, email)
    assert user is not None
    assert user.role == "developer"
    assert user.display_name == "Ada Lovelace"


async def test_cli_create_user_normalizes_email(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)

    await admin_cli._create_user("  Ada  ", "  MiXeD@Example.TEST ", "readonly")

    user = await provisioning_service.get_user_by_email(db_session, "mixed@example.test")
    assert user is not None
    assert user.display_name == "Ada"
    assert user.role == "readonly"


async def test_cli_create_user_duplicate_email_conflicts(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)
    email = f"{uuid.uuid4()}@example.test"
    await admin_cli._create_user("First", email, "developer")

    with pytest.raises(HTTPException) as exc_info:
        await admin_cli._create_user("Second", email, "developer")

    assert exc_info.value.status_code == 409


async def test_cli_set_password(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_session(monkeypatch, db_session)
    user = await provisioning_service.create_user(
        db_session, "User", f"{uuid.uuid4()}@example.test", "developer"
    )

    await admin_cli._set_password(user.email, "correct horse battery")

    assert await provisioning_service.verify_user_password(
        db_session, user.email, "correct horse battery"
    )
    assert await provisioning_service.verify_user_password(db_session, user.email, "wrong") is None


async def test_cli_bootstrap_admin_sets_password(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)
    email = f"{uuid.uuid4()}@example.test"

    await admin_cli._bootstrap_admin("Root Admin", email, "bootstrap-pass")

    user = await provisioning_service.get_user_by_email(db_session, email)
    assert user is not None
    assert user.role == "admin"
    assert await provisioning_service.verify_user_password(db_session, email, "bootstrap-pass")


async def test_cli_bootstrap_admin_rejects_second_admin(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)

    await admin_cli._bootstrap_admin("First", f"{uuid.uuid4()}@example.test", None)
    with pytest.raises(HTTPException) as exc_info:
        await admin_cli._bootstrap_admin("Second", f"{uuid.uuid4()}@example.test", None)

    assert exc_info.value.status_code == 409


async def test_cli_machine_create(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _bind_session(monkeypatch, db_session)
    user = await provisioning_service.create_user(
        db_session, "User", f"{uuid.uuid4()}@example.test", "developer"
    )

    await admin_cli._create_machine(user.email, "flo-desktop")

    out = capsys.readouterr().out
    assert "machine created" in out
    assert "token (store now, never shown again):" in out
    machine = (
        await db_session.execute(select(MachineModel).where(MachineModel.owner_user_id == user.id))
    ).scalar_one()
    assert machine.display_name == "flo-desktop"


async def test_cli_machine_create_unknown_owner(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)

    with pytest.raises(SystemExit) as exc_info:
        await admin_cli._create_machine(f"{uuid.uuid4()}@example.test", "ghost")

    assert exc_info.value.code == 1


def test_main_dispatches_user_create_and_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []

    async def fake_create_user(display_name: str, email: str, role: str) -> None:
        calls.append((display_name, email, role))

    monkeypatch.setattr(admin_cli, "_create_user", fake_create_user)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "studio-admin",
            "user",
            "create",
            "--display-name",
            "Ada",
            "--email",
            "MiXeD@Example.TEST",
            "--role",
            "admin",
        ],
    )

    admin_cli.main()

    assert calls == [("Ada", "mixed@example.test", "admin")]


def test_main_rejects_invalid_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "studio-admin",
            "user",
            "create",
            "--display-name",
            "Ada",
            "--email",
            "ada@example.test",
            "--role",
            "root",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main()

    assert exc_info.value.code == 2


def test_main_rejects_invalid_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "studio-admin",
            "user",
            "create",
            "--display-name",
            "Ada",
            "--email",
            "not-an-email",
            "--role",
            "developer",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main()

    assert exc_info.value.code == 2


def test_main_rejects_empty_display_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "studio-admin",
            "user",
            "create",
            "--display-name",
            "   ",
            "--email",
            "ada@example.test",
            "--role",
            "developer",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main()

    assert exc_info.value.code == 2


def test_main_dispatches_set_password_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_set_password(email: str, password: str) -> None:
        calls.append((email, password))

    monkeypatch.setattr(admin_cli, "_set_password", fake_set_password)
    monkeypatch.setattr(sys, "stdin", io.StringIO("stdin-secret\n"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["studio-admin", "set-password", "--email", "ada@example.test", "--password-stdin"],
    )

    admin_cli.main()

    assert calls == [("ada@example.test", "stdin-secret")]


def test_main_set_password_keeps_password_argument_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_set_password(email: str, password: str) -> None:
        calls.append((email, password))

    monkeypatch.setattr(admin_cli, "_set_password", fake_set_password)
    monkeypatch.setattr(
        sys,
        "argv",
        ["studio-admin", "set-password", "--email", "ada@example.test", "--password", "legacy"],
    )

    admin_cli.main()

    assert calls == [("ada@example.test", "legacy")]


def test_main_set_password_requires_a_password_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["studio-admin", "set-password", "--email", "ada@example.test"]
    )

    with pytest.raises(SystemExit) as exc_info:
        admin_cli.main()

    assert exc_info.value.code == 2


def test_read_password_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("s3cret-pass\n"))
    assert admin_cli._read_password_from_stdin() == "s3cret-pass"


def test_read_password_from_stdin_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as exc_info:
        admin_cli._read_password_from_stdin()
    assert exc_info.value.code == 1


async def test_workflow_user_password_machine(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)
    email = f"{uuid.uuid4()}@example.test"

    await admin_cli._create_user("Flo", email, "developer")
    await admin_cli._set_password(email, "workflow-pass")
    await admin_cli._create_machine(email, "flo-desktop")

    user = await provisioning_service.get_user_by_email(db_session, email)
    assert user is not None
    assert await provisioning_service.verify_user_password(db_session, email, "workflow-pass")
    machine = (
        await db_session.execute(select(MachineModel).where(MachineModel.owner_user_id == user.id))
    ).scalar_one()
    assert machine.display_name == "flo-desktop"


async def test_workflow_existing_user_can_still_get_a_machine(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)
    email = f"{uuid.uuid4()}@example.test"
    await admin_cli._create_user("Flo", email, "developer")

    with pytest.raises(HTTPException):
        await admin_cli._create_user("Flo Again", email, "admin")

    user = await provisioning_service.get_user_by_email(db_session, email)
    assert user is not None
    assert user.role == "developer"

    await admin_cli._create_machine(email, "second-desktop")
    machines = (
        (
            await db_session.execute(
                select(MachineModel).where(MachineModel.owner_user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert [machine.display_name for machine in machines] == ["second-desktop"]


async def test_workflow_password_failure_leaves_no_machine(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)
    email = f"{uuid.uuid4()}@example.test"

    await admin_cli._create_user("Flo", email, "developer")

    async def _boom(session: AsyncSession, email: str, password: str) -> None:
        raise HTTPException(500, "password store unavailable")

    monkeypatch.setattr(provisioning_service, "set_user_password", _boom)

    with pytest.raises(HTTPException):
        await admin_cli._set_password(email, "workflow-pass")

    user = await provisioning_service.get_user_by_email(db_session, email)
    assert user is not None
    assert user.password_hash is None
    machines = (
        (
            await db_session.execute(
                select(MachineModel).where(MachineModel.owner_user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert machines == []


async def test_workflow_no_machine_requested(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_session(monkeypatch, db_session)
    email = f"{uuid.uuid4()}@example.test"

    await admin_cli._create_user("Flo", email, "developer")
    await admin_cli._set_password(email, "workflow-pass")

    user = await provisioning_service.get_user_by_email(db_session, email)
    assert user is not None
    machines = (
        (
            await db_session.execute(
                select(MachineModel).where(MachineModel.owner_user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert machines == []
