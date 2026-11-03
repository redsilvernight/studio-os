from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.usage import UsageLedgerEntryModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_contracts.usage import (
    CONFIGURATION_HISTORY_MAX_GROUPS,
    CONFIGURATION_MIXED,
    ConfigurationHistory,
    ConfigurationRateKey,
    UsageTotalStatus,
)

from tests.api.test_launch_credentials import _accepted_launch, _credential

HISTORY = "/api/v1/usage/configuration-history"
SINCE = datetime(2026, 10, 10, tzinfo=UTC)
UNTIL = datetime(2026, 10, 17, tzinfo=UTC)


async def _history(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID, **params: str
) -> ConfigurationHistory:
    response = await client.get(
        HISTORY, headers=headers, params={"project_id": str(project_id), **params}
    )
    assert response.status_code == 200, response.text
    return ConfigurationHistory.model_validate(response.json())


async def _task(db_session: AsyncSession, project_id: uuid.UUID) -> TaskModel:
    task = TaskModel(project_id=project_id, title="Config history")
    db_session.add(task)
    await db_session.flush()
    return task


async def _session(
    db_session: AsyncSession, task: TaskModel, machine: MachineModel, *, started_at: datetime
) -> WorkSessionModel:
    work_session = WorkSessionModel(task_id=task.id, machine_id=machine.id, started_at=started_at)
    db_session.add(work_session)
    await db_session.flush()
    return work_session


async def _launch(
    db_session: AsyncSession,
    project_id: uuid.UUID,
    task: TaskModel,
    machine: MachineModel,
    *,
    created_at: datetime,
    harness_id: str = "claude-code",
    status: str = "succeeded",
    session_id: uuid.UUID | None = None,
    profile_key: str | None = None,
    profile_contract_version: int | None = None,
    profile_digest: str | None = None,
) -> TaskLaunchModel:
    launch = TaskLaunchModel(
        project_id=project_id,
        task_id=task.id,
        machine_id=machine.id,
        requested_by_user_id=machine.owner_user_id,
        harness_id=harness_id,
        status=status,
        created_at=created_at,
        finished_at=created_at + timedelta(minutes=1),
        expires_at=created_at + timedelta(hours=1),
        session_id=session_id,
        profile_key=profile_key,
        profile_contract_version=profile_contract_version,
        profile_digest=profile_digest,
    )
    db_session.add(launch)
    await db_session.flush()
    return launch


async def _ledger(
    db_session: AsyncSession, project_id: uuid.UUID, machine_id: uuid.UUID, **columns: Any
) -> UsageLedgerEntryModel:
    period_start = columns.pop("period_start", SINCE + timedelta(hours=1))
    period_end = columns.pop("period_end", period_start + timedelta(seconds=5))
    entry = UsageLedgerEntryModel(
        project_id=project_id,
        machine_id=machine_id,
        source_event_id=f"evt-{uuid.uuid4().hex}",
        collector="runtime",
        period_start=period_start,
        period_end=period_end,
        **columns,
    )
    db_session.add(entry)
    await db_session.flush()
    return entry


async def _ai_work(
    db_session: AsyncSession,
    project_id: uuid.UUID,
    machine: MachineModel,
    agent: AgentModel,
    task: TaskModel,
    *,
    session_id: uuid.UUID | None,
    started_at: datetime,
) -> AIWorkLogModel:
    work = AIWorkLogModel(
        project_id=project_id,
        task_id=task.id,
        machine_id=machine.id,
        agent_id=agent.id,
        session_id=session_id,
        summary="work",
        started_at=started_at,
    )
    db_session.add(work)
    await db_session.flush()
    return work


async def test_groups_order_unknown_last_and_rates_are_none_at_zero_denominator(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    task = await _task(db_session, project.id)
    work_session = await _session(
        db_session, task, machine_model, started_at=SINCE + timedelta(minutes=10)
    )
    known = await _launch(
        db_session,
        project.id,
        task,
        machine_model,
        created_at=SINCE + timedelta(hours=1),
        session_id=work_session.id,
    )
    await _ledger(
        db_session,
        project.id,
        machine_model.id,
        task_launch_id=known.id,
        harness_version="2.1.0",
        provider="anthropic",
        model="opus",
        tokens_in=100,
        tokens_in_coverage="measured",
        tokens_out=20,
        tokens_out_coverage="measured",
        cost=Decimal("0.50"),
        cost_coverage="measured",
        cost_currency="USD",
    )
    await _launch(
        db_session,
        project.id,
        task,
        machine_model,
        created_at=SINCE + timedelta(hours=2),
        harness_id="codex",
        status="running",
    )

    history = await _history(
        client, auth_headers, project.id, since=SINCE.isoformat(), until=UNTIL.isoformat()
    )
    assert history.population == "task_launch"
    assert history.ranking == "none"
    assert history.launches == 2 and history.truncated is False
    assert [set(item) for item in [history.caveats]] == [
        {"tests_not_quality", "not_ranked", "no_minimum_sample", "ledger_derived_fields"}
    ]

    first, second = history.groups
    assert first.key.harness == "claude-code" and first.key.model == "opus"
    assert first.comparable is False
    assert [rate.key for rate in first.rates] == [
        ConfigurationRateKey.SUCCEEDED,
        ConfigurationRateKey.SESSION_LINKED,
        ConfigurationRateKey.USAGE_MEASURED,
    ]
    known_rates = {rate.key: rate for rate in first.rates}
    assert known_rates[ConfigurationRateKey.SUCCEEDED].value == 1.0
    assert known_rates[ConfigurationRateKey.SESSION_LINKED].value == 1.0
    assert known_rates[ConfigurationRateKey.USAGE_MEASURED].value == 1.0
    assert all(rate.definition for rate in first.rates)
    assert first.total_tokens.known_sum == 120
    assert first.total_tokens.status is UsageTotalStatus.EXACT
    assert first.cost.known_sum == Decimal("0.50") and first.cost.currency == "USD"
    assert first.ledger_entries == 1

    assert second.key.harness == "codex"
    assert second.key.harness_version is None
    assert second.key.provider is None and second.key.model is None
    assert second.key.profile_key is None and second.key.profile_contract_version is None
    unknown_rates = {rate.key: rate for rate in second.rates}
    succeeded = unknown_rates[ConfigurationRateKey.SUCCEEDED]
    assert succeeded.denominator == 0 and succeeded.value is None
    assert succeeded.covered == 0 and succeeded.launches == 1
    assert unknown_rates[ConfigurationRateKey.SESSION_LINKED].value == 0.0
    assert unknown_rates[ConfigurationRateKey.USAGE_MEASURED].denominator == 1
    assert unknown_rates[ConfigurationRateKey.USAGE_MEASURED].value == 0.0
    assert second.total_tokens.known_sum is None
    assert second.total_tokens.status is UsageTotalStatus.NONE
    assert second.cost.known_sum is None


async def test_ledger_derived_fields_are_mixed_when_entries_disagree(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    task = await _task(db_session, project.id)
    digest = "sha256:" + "a" * 64
    launch = await _launch(
        db_session,
        project.id,
        task,
        machine_model,
        created_at=SINCE + timedelta(hours=1),
        profile_key="coding",
        profile_contract_version=2,
        profile_digest=digest,
    )
    await _ledger(
        db_session,
        project.id,
        machine_model.id,
        task_launch_id=launch.id,
        harness_version="2.1.0",
        provider="anthropic",
        model="opus",
    )
    await _ledger(
        db_session,
        project.id,
        machine_model.id,
        task_launch_id=launch.id,
        provider="anthropic",
        model="sonnet",
    )

    history = await _history(
        client, auth_headers, project.id, since=SINCE.isoformat(), until=UNTIL.isoformat()
    )
    assert history.launches == 1
    group = history.groups[0]
    assert group.key.harness == "claude-code"
    assert group.key.profile_key == "coding"
    assert group.key.profile_contract_version == 2
    assert group.key.profile_digest == digest
    assert group.key.harness_version == "2.1.0"
    assert group.key.provider == "anthropic"
    assert group.key.model == CONFIGURATION_MIXED
    assert group.ledger_entries == 2


async def test_unattributed_ledger_and_ai_work_are_reported_never_grouped(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    task = await _task(db_session, project.id)
    work_session = await _session(
        db_session, task, machine_model, started_at=SINCE + timedelta(minutes=10)
    )
    launch = await _launch(
        db_session,
        project.id,
        task,
        machine_model,
        created_at=SINCE + timedelta(hours=1),
        session_id=work_session.id,
    )
    await _ledger(
        db_session,
        project.id,
        machine_model.id,
        task_launch_id=launch.id,
        tokens_in=10,
        tokens_in_coverage="measured",
        tokens_out=5,
        tokens_out_coverage="measured",
    )
    await _ledger(db_session, project.id, machine_model.id)
    outside = await _launch(
        db_session,
        project.id,
        task,
        machine_model,
        created_at=SINCE - timedelta(days=1),
    )
    await _ledger(db_session, project.id, machine_model.id, task_launch_id=outside.id)
    await _ai_work(
        db_session,
        project.id,
        machine_model,
        agent,
        task,
        session_id=work_session.id,
        started_at=SINCE + timedelta(minutes=20),
    )
    await _ai_work(
        db_session,
        project.id,
        machine_model,
        agent,
        task,
        session_id=work_session.id,
        started_at=SINCE - timedelta(days=1),
    )
    await _ai_work(
        db_session,
        project.id,
        machine_model,
        agent,
        task,
        session_id=None,
        started_at=SINCE + timedelta(minutes=30),
    )
    await _ai_work(
        db_session,
        project.id,
        machine_model,
        agent,
        task,
        session_id=None,
        started_at=SINCE - timedelta(days=1),
    )

    history = await _history(
        client, auth_headers, project.id, since=SINCE.isoformat(), until=UNTIL.isoformat()
    )
    assert history.launches == 1
    group = history.groups[0]
    assert group.ledger_entries == 1
    assert group.ai_work_entries == 2
    assert history.unattributed.ledger_entries == 1
    assert history.unattributed.ai_work_entries == 1


async def test_groups_are_capped_and_marked_truncated(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    task = await _task(db_session, project.id)
    for index in range(CONFIGURATION_HISTORY_MAX_GROUPS + 1):
        await _launch(
            db_session,
            project.id,
            task,
            machine_model,
            created_at=SINCE + timedelta(minutes=index),
            harness_id=f"harness-{index:03d}",
        )

    history = await _history(
        client, auth_headers, project.id, since=SINCE.isoformat(), until=UNTIL.isoformat()
    )
    assert history.launches == CONFIGURATION_HISTORY_MAX_GROUPS + 1
    assert history.truncated is True
    assert len(history.groups) == CONFIGURATION_HISTORY_MAX_GROUPS
    assert [group.key.harness for group in history.groups] == [
        f"harness-{index:03d}" for index in range(CONFIGURATION_HISTORY_MAX_GROUPS)
    ]


async def test_access_and_period_validation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    project_id, launch_id, _ = await _accepted_launch(client, auth_headers, machine)
    ephemeral = await _credential(client, auth_headers, launch_id)
    denied = await client.get(HISTORY, headers=ephemeral, params={"project_id": project_id})
    assert denied.status_code == 403, denied.text

    assert (await client.get(HISTORY, headers=auth_headers)).status_code == 422
    inverted = await client.get(
        HISTORY,
        headers=auth_headers,
        params={
            "project_id": str(project.id),
            "since": UNTIL.isoformat(),
            "until": SINCE.isoformat(),
        },
    )
    assert inverted.status_code == 422
    assert inverted.json()["detail"]["error_code"] == "invalid_usage_period"
