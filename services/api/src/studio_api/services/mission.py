"""Mission Control read model (DEC-0196, P02-read-model).

A bounded, read-only projection built at read time from existing sources
only — TaskLaunch, WorkSession, AIWorkLog, resource claims, machines and
proposed decisions. Nothing is persisted: no new session entity, no
parallel state, no write at all.

Two rules shape the module:

- The truth table of `studio_contracts.mission` lives in `evaluate_run`, a
  pure function over resolved facts. Nothing else decides a verdict, and it
  never touches the database or the clock, so every row is testable alone.
- The number of SQL statements is fixed — one per source, each grouped by
  `IN`, whatever the number of runs. There is no per-run query.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.ai_work import AIWorkStatus
from studio_contracts.auth import MachineStatus
from studio_contracts.decisions import DecisionStatus
from studio_contracts.mission import (
    MISSION_DEFAULT_LIMIT,
    MissionCounts,
    MissionDataGap,
    MissionHandoffRef,
    MissionLaunchRef,
    MissionProtocolState,
    MissionReason,
    MissionRun,
    MissionSessionRef,
    MissionVerdict,
    ProjectMission,
)
from studio_contracts.sessions import SessionStatus
from studio_contracts.task_launch import TERMINAL_STATUSES, TaskLaunchReasonCode, TaskLaunchStatus

from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import heartbeats as heartbeats_service
from studio_api.services import sessions as sessions_service
from studio_api.services.authz import Principal, ensure_project_access
from studio_api.settings import Settings, get_settings

MISSION_DEFAULT_WINDOW_HOURS = 168

_TERMINAL_LAUNCH_STATUSES = frozenset(TERMINAL_STATUSES)
_PENDING_LAUNCH_STATUSES = frozenset(
    {TaskLaunchStatus.REQUESTED, TaskLaunchStatus.ACCEPTED, TaskLaunchStatus.PREPARING}
)
_LAUNCH_FAILURE_REASONS: dict[TaskLaunchStatus, MissionReason] = {
    TaskLaunchStatus.FAILED: MissionReason.LAUNCH_FAILED,
    TaskLaunchStatus.REJECTED: MissionReason.LAUNCH_REJECTED,
    TaskLaunchStatus.EXPIRED: MissionReason.LAUNCH_EXPIRED,
}
_ACTIVE_CLAIM_STATUS = "active"
_STARTED_AI_WORK = AIWorkStatus.STARTED.value
_REVIEW_REQUESTED_AI_WORK = AIWorkStatus.REVIEW_REQUESTED.value


@dataclass(frozen=True)
class RunFacts:
    """The resolved state one run is judged on. The only input
    `evaluate_run` reads, which is what keeps the truth table independent of
    the database."""

    source: Literal["launch", "session"]
    launch_status: TaskLaunchStatus | None
    session_status: SessionStatus | None
    handed_off: bool
    review_requested_on_session: bool
    review_requested_on_task: bool
    decision_proposed: bool
    machine_offline: bool


@dataclass(frozen=True)
class MissionEvaluation:
    verdict: MissionVerdict
    reasons: list[MissionReason]
    protocol_state: MissionProtocolState


def protocol_state_of(facts: RunFacts) -> MissionProtocolState:
    """Protocol closure, reported apart from the process result (DEC-0201):
    a session that ended without a non-`started` AIWork entry was never
    handed off, whatever the launch reported."""
    if facts.session_status is None:
        return MissionProtocolState.MISSING
    if facts.session_status is not SessionStatus.ENDED:
        return MissionProtocolState.OPEN
    if facts.handed_off:
        return MissionProtocolState.HANDED_OFF
    return MissionProtocolState.ENDED_WITHOUT_HANDOFF


def _running_reason(
    launch: TaskLaunchStatus | None, session: SessionStatus | None
) -> MissionReason:
    """Row 12. A launch still `running` is a running process whatever the
    session does; without a launch the session carries the run, so only its
    idleness is worth reporting."""
    if launch is not TaskLaunchStatus.RUNNING and session is SessionStatus.IDLE:
        return MissionReason.SESSION_IDLE
    return MissionReason.PROCESS_RUNNING


def _is_open(facts: RunFacts) -> bool:
    """Still in flight: a non-terminal launch, or a session that has not
    ended. A finished launch whose session is gone is not open."""
    if facts.launch_status is not None and facts.launch_status not in _TERMINAL_LAUNCH_STATUSES:
        return True
    return facts.session_status is not None and facts.session_status is not SessionStatus.ENDED


def evaluate_run(facts: RunFacts) -> MissionEvaluation:
    """The truth table of `studio_contracts.mission`, evaluated top to bottom.

    First match wins the verdict; every matching row contributes its reason,
    the winning one first, so a discordant state stays visible.
    """
    launch = facts.launch_status
    session = facts.session_status
    protocol = protocol_state_of(facts)
    matched: list[tuple[MissionVerdict, list[MissionReason]]] = []

    if launch is TaskLaunchStatus.CANCELLED:
        matched.append((MissionVerdict.CANCELLED, [MissionReason.LAUNCH_CANCELLED]))
    failure_reason = _LAUNCH_FAILURE_REASONS.get(launch) if launch is not None else None
    if failure_reason is not None:
        matched.append((MissionVerdict.FAILED, [failure_reason]))
    if facts.review_requested_on_session or (session is None and facts.review_requested_on_task):
        matched.append((MissionVerdict.WAITING_HUMAN, [MissionReason.REVIEW_REQUESTED]))
    if facts.decision_proposed:
        matched.append((MissionVerdict.WAITING_HUMAN, [MissionReason.DECISION_PROPOSED]))
    if protocol is MissionProtocolState.HANDED_OFF:
        matched.append((MissionVerdict.DONE, [MissionReason.HANDED_OFF]))
    if launch is TaskLaunchStatus.SUCCEEDED:
        if protocol is MissionProtocolState.MISSING:
            exited: list[MissionReason] = [MissionReason.PROCESS_EXITED_WITHOUT_SESSION]
        elif protocol is MissionProtocolState.ENDED_WITHOUT_HANDOFF:
            exited = [MissionReason.SESSION_ENDED_WITHOUT_HANDOFF]
        elif protocol is MissionProtocolState.OPEN:
            exited = [MissionReason.PROCESS_EXITED_SESSION_OPEN]
        else:
            exited = []
        if exited:
            matched.append((MissionVerdict.NEEDS_ATTENTION, exited))
    stale: list[MissionReason] = []
    if session is SessionStatus.EXPIRED:
        stale.append(MissionReason.SESSION_EXPIRED)
    if facts.machine_offline and _is_open(facts):
        stale.append(MissionReason.MACHINE_OFFLINE)
    if stale:
        matched.append((MissionVerdict.STALE, stale))
    if launch is None and protocol is MissionProtocolState.ENDED_WITHOUT_HANDOFF:
        matched.append(
            (MissionVerdict.NEEDS_ATTENTION, [MissionReason.SESSION_ENDED_WITHOUT_HANDOFF])
        )
    if launch in _PENDING_LAUNCH_STATUSES:
        matched.append((MissionVerdict.PENDING, [MissionReason.LAUNCH_PENDING]))
    if not matched:
        matched.append((MissionVerdict.RUNNING, [_running_reason(launch, session)]))

    return MissionEvaluation(
        verdict=matched[0][0],
        reasons=[reason for _verdict, row in matched for reason in row],
        protocol_state=protocol,
    )


def _invalid_cursor() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_cursor"},
    )


def _encode_cursor(updated_at: datetime, run_id: uuid.UUID) -> str:
    payload = json.dumps({"u": updated_at.isoformat(), "i": str(run_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        return datetime.fromisoformat(payload["u"]), uuid.UUID(payload["i"])
    except (ValueError, KeyError, TypeError) as exc:
        raise _invalid_cursor() from exc


@dataclass(frozen=True)
class _Candidate:
    source: Literal["launch", "session"]
    run_id: uuid.UUID
    task_id: uuid.UUID
    machine_id: uuid.UUID
    launch: TaskLaunchModel | None
    work_session: WorkSessionModel | None


def _launches_stmt(project_id: uuid.UUID, since: datetime) -> Any:
    return select(TaskLaunchModel).where(
        TaskLaunchModel.project_id == project_id,
        or_(TaskLaunchModel.created_at >= since, TaskLaunchModel.finished_at >= since),
    )


def _sessions_stmt(project_id: uuid.UUID, since: datetime) -> Any:
    """Sessions of the project inside the window, plus the ones a windowed
    launch links to. A session no launch of the project references is a
    manual run; one an out-of-window launch references belongs to that launch
    and never shows up on its own."""
    linked_here = exists().where(
        TaskLaunchModel.session_id == WorkSessionModel.id,
        TaskLaunchModel.project_id == project_id,
    )
    linked_in_window = exists().where(
        TaskLaunchModel.session_id == WorkSessionModel.id,
        TaskLaunchModel.project_id == project_id,
        or_(TaskLaunchModel.created_at >= since, TaskLaunchModel.finished_at >= since),
    )
    return (
        select(WorkSessionModel)
        .join(TaskModel, TaskModel.id == WorkSessionModel.task_id)
        .where(
            TaskModel.project_id == project_id,
            or_(
                and_(
                    ~linked_here,
                    or_(
                        WorkSessionModel.started_at >= since,
                        WorkSessionModel.ended_at >= since,
                    ),
                ),
                linked_in_window,
            ),
        )
    )


async def _tasks_by_id(
    session: AsyncSession, task_ids: set[uuid.UUID]
) -> dict[uuid.UUID, TaskModel]:
    if not task_ids:
        return {}
    stmt = select(TaskModel).where(TaskModel.id.in_(task_ids))
    rows: Sequence[TaskModel] = (await session.execute(stmt)).scalars().all()
    return {row.id: row for row in rows}


async def _ai_work_in_scope(
    session: AsyncSession,
    project_id: uuid.UUID,
    task_ids: set[uuid.UUID],
    session_ids: set[uuid.UUID],
) -> list[AIWorkLogModel]:
    """The entries a run can be judged on: those attached to one of its
    sessions (handoff, review) or to one of its tasks (review with no
    session)."""
    scopes = []
    if session_ids:
        scopes.append(AIWorkLogModel.session_id.in_(session_ids))
    if task_ids:
        scopes.append(AIWorkLogModel.task_id.in_(task_ids))
    if not scopes:
        return []
    stmt = select(AIWorkLogModel).where(AIWorkLogModel.project_id == project_id, or_(*scopes))
    rows: Sequence[AIWorkLogModel] = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def _proposed_decision_tasks(
    session: AsyncSession, project_id: uuid.UUID, task_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    if not task_ids:
        return set()
    stmt = select(DecisionModel.task_id).where(
        DecisionModel.project_id == project_id,
        DecisionModel.status == DecisionStatus.PROPOSED.value,
        DecisionModel.task_id.in_(task_ids),
    )
    rows: Sequence[uuid.UUID | None] = (await session.execute(stmt)).scalars().all()
    return {task_id for task_id in rows if task_id is not None}


async def _active_claim_counts(
    session: AsyncSession, project_id: uuid.UUID, task_ids: set[uuid.UUID], now: datetime
) -> dict[uuid.UUID, int]:
    """Same filter as the claims service: an expired claim is not active,
    whatever its `status` reads."""
    if not task_ids:
        return {}
    stmt = (
        select(ResourceClaimModel.task_id, func.count())
        .where(
            ResourceClaimModel.project_id == project_id,
            ResourceClaimModel.status == _ACTIVE_CLAIM_STATUS,
            ResourceClaimModel.expires_at > now,
            ResourceClaimModel.task_id.in_(task_ids),
        )
        .group_by(ResourceClaimModel.task_id)
    )
    rows = (await session.execute(stmt)).all()
    counts: dict[uuid.UUID, int] = {}
    for row in rows:
        task_id = row[0]
        if task_id is not None:
            counts[task_id] = row[1]
    return counts


async def _machines_by_id(
    session: AsyncSession, machine_ids: set[uuid.UUID]
) -> dict[uuid.UUID, MachineModel]:
    if not machine_ids:
        return {}
    stmt = select(MachineModel).where(MachineModel.id.in_(machine_ids))
    rows: Sequence[MachineModel] = (await session.execute(stmt)).scalars().all()
    return {row.id: row for row in rows}


def _candidates(
    launches: Sequence[TaskLaunchModel], work_sessions: Sequence[WorkSessionModel]
) -> list[_Candidate]:
    """One run per launch, plus one per session no launch references."""
    by_session_id = {work_session.id: work_session for work_session in work_sessions}
    linked: set[uuid.UUID] = set()
    candidates: list[_Candidate] = []
    for launch in launches:
        session_id = launch.session_id
        attached = (
            by_session_id.get(session_id)
            if session_id is not None and session_id not in linked
            else None
        )
        if attached is not None:
            linked.add(attached.id)
        candidates.append(
            _Candidate(
                source="launch",
                run_id=launch.id,
                task_id=launch.task_id,
                machine_id=launch.machine_id,
                launch=launch,
                work_session=attached,
            )
        )
    for work_session in work_sessions:
        if work_session.id in linked:
            continue
        candidates.append(
            _Candidate(
                source="session",
                run_id=work_session.id,
                task_id=work_session.task_id,
                machine_id=work_session.machine_id,
                launch=None,
                work_session=work_session,
            )
        )
    return candidates


def _updated_at(candidate: _Candidate) -> datetime:
    """Newest thing that happened to the run — the ordering key, built from
    the columns because `work_sessions` carries no `updated_at`."""
    stamps: list[datetime] = []
    if candidate.launch is not None:
        stamps.append(candidate.launch.created_at)
        if candidate.launch.finished_at is not None:
            stamps.append(candidate.launch.finished_at)
    if candidate.work_session is not None:
        stamps.append(candidate.work_session.started_at)
        for stamp in (candidate.work_session.last_activity_at, candidate.work_session.ended_at):
            if stamp is not None:
                stamps.append(stamp)
    return max(stamps)


def _build_run(
    candidate: _Candidate,
    *,
    tasks: dict[uuid.UUID, TaskModel],
    machines: dict[uuid.UUID, MachineModel],
    review_on_session: set[uuid.UUID],
    review_on_task: set[uuid.UUID],
    handoff_by_session: dict[uuid.UUID, AIWorkLogModel],
    decision_tasks: set[uuid.UUID],
    claim_counts: dict[uuid.UUID, int],
    settings: Settings,
) -> MissionRun:
    launch = candidate.launch
    work_session = candidate.work_session
    task = tasks.get(candidate.task_id)
    machine = machines.get(candidate.machine_id)
    machine_status = (
        heartbeats_service.derive_status(machine, settings) if machine is not None else None
    )
    session_status = (
        sessions_service.derive_session_status(work_session, settings)
        if work_session is not None
        else None
    )
    handoff = handoff_by_session.get(work_session.id) if work_session is not None else None

    evaluation = evaluate_run(
        RunFacts(
            source=candidate.source,
            launch_status=TaskLaunchStatus(launch.status) if launch is not None else None,
            session_status=session_status,
            handed_off=handoff is not None,
            review_requested_on_session=(
                work_session is not None and work_session.id in review_on_session
            ),
            review_requested_on_task=candidate.task_id in review_on_task,
            decision_proposed=candidate.task_id in decision_tasks,
            machine_offline=machine_status is MachineStatus.OFFLINE,
        )
    )

    gaps: list[MissionDataGap] = []
    if machine is None:
        gaps.append(MissionDataGap.MACHINE_UNKNOWN)
    if launch is not None and launch.session_id is not None and work_session is None:
        gaps.append(MissionDataGap.SESSION_NOT_FOUND)
    if task is None:
        gaps.append(MissionDataGap.TASK_NOT_FOUND)

    return MissionRun(
        run_id=candidate.run_id,
        source=candidate.source,
        task_id=candidate.task_id,
        task_title=task.title if task is not None else None,
        task_status=task.status if task is not None else None,
        machine_id=candidate.machine_id,
        machine_status=machine_status,
        launch=(
            MissionLaunchRef(
                id=launch.id,
                status=TaskLaunchStatus(launch.status),
                reason_code=TaskLaunchReasonCode(launch.reason_code),
                harness_id=launch.harness_id,
                created_at=launch.created_at,
                finished_at=launch.finished_at,
            )
            if launch is not None
            else None
        ),
        session=(
            MissionSessionRef(
                id=work_session.id,
                status=session_status,
                agent_id=work_session.agent_id,
                started_at=work_session.started_at,
                ended_at=work_session.ended_at,
                last_activity_at=work_session.last_activity_at,
            )
            if work_session is not None and session_status is not None
            else None
        ),
        handoff=(
            MissionHandoffRef(
                ai_work_id=handoff.id,
                status=AIWorkStatus(handoff.status),
                summary=handoff.summary,
                completed_at=handoff.ended_at,
            )
            if handoff is not None
            else None
        ),
        protocol_state=evaluation.protocol_state,
        verdict=evaluation.verdict,
        reasons=evaluation.reasons,
        active_claims=claim_counts.get(candidate.task_id, 0),
        data_gaps=gaps,
        updated_at=_updated_at(candidate),
    )


def _classify_ai_work(
    entries: Sequence[AIWorkLogModel],
) -> tuple[set[uuid.UUID], set[uuid.UUID], dict[uuid.UUID, AIWorkLogModel]]:
    """`review_requested` per session and per task, and the earliest
    non-`started` entry per session — what `studio_handoff` writes, and what
    makes a protocol closure a handoff."""
    review_on_session: set[uuid.UUID] = set()
    review_on_task: set[uuid.UUID] = set()
    handoff_by_session: dict[uuid.UUID, AIWorkLogModel] = {}
    for entry in entries:
        if entry.status == _REVIEW_REQUESTED_AI_WORK:
            if entry.session_id is not None:
                review_on_session.add(entry.session_id)
            if entry.task_id is not None:
                review_on_task.add(entry.task_id)
        if entry.session_id is None or entry.status == _STARTED_AI_WORK:
            continue
        current = handoff_by_session.get(entry.session_id)
        if current is None or (entry.started_at, entry.id) < (current.started_at, current.id):
            handoff_by_session[entry.session_id] = entry
    return review_on_session, review_on_task, handoff_by_session


async def get_project_mission(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    window_hours: int = MISSION_DEFAULT_WINDOW_HOURS,
    limit: int = MISSION_DEFAULT_LIMIT,
    cursor: str | None = None,
) -> ProjectMission:
    """The project's executions, bounded to `window_hours` and projected at
    read time from launches, sessions, AI work, claims, machines and proposed
    decisions — nothing is written and no new state exists, the verdict comes
    from `evaluate_run` alone.

    One run per TaskLaunch, plus one per work session no launch references.
    Runs are ordered `updated_at` descending then `run_id` ascending, and
    paged with an opaque cursor; `counts` always covers the whole window, not
    only the returned page. An inaccessible `project_id` answers 403 before
    anything is read (DEC-0103 §7).
    """
    ensure_project_access(principal, project_id)
    settings = get_settings()
    now = datetime.now(UTC)
    since = now - timedelta(hours=window_hours)

    launches: list[TaskLaunchModel] = list(
        (await session.execute(_launches_stmt(project_id, since))).scalars().all()
    )
    work_sessions: list[WorkSessionModel] = list(
        (await session.execute(_sessions_stmt(project_id, since))).scalars().all()
    )
    candidates = _candidates(launches, work_sessions)

    task_ids = {candidate.task_id for candidate in candidates}
    session_ids = {
        candidate.work_session.id for candidate in candidates if candidate.work_session is not None
    }
    machine_ids = {candidate.machine_id for candidate in candidates}
    tasks = await _tasks_by_id(session, task_ids)
    machines = await _machines_by_id(session, machine_ids)
    review_on_session, review_on_task, handoff_by_session = _classify_ai_work(
        await _ai_work_in_scope(session, project_id, task_ids, session_ids)
    )
    decision_tasks = await _proposed_decision_tasks(session, project_id, task_ids)
    claim_counts = await _active_claim_counts(session, project_id, task_ids, now)

    runs = [
        _build_run(
            candidate,
            tasks=tasks,
            machines=machines,
            review_on_session=review_on_session,
            review_on_task=review_on_task,
            handoff_by_session=handoff_by_session,
            decision_tasks=decision_tasks,
            claim_counts=claim_counts,
            settings=settings,
        )
        for candidate in candidates
    ]
    runs.sort(key=lambda run: run.run_id)
    runs.sort(key=lambda run: run.updated_at, reverse=True)

    by_verdict: dict[MissionVerdict, int] = {}
    for run in runs:
        by_verdict[run.verdict] = by_verdict.get(run.verdict, 0) + 1
    counts = MissionCounts(by_verdict=by_verdict, total=len(runs))

    remaining = runs
    if cursor is not None:
        cursor_updated_at, cursor_run_id = _decode_cursor(cursor)
        remaining = [
            run
            for run in runs
            if run.updated_at < cursor_updated_at
            or (run.updated_at == cursor_updated_at and run.run_id > cursor_run_id)
        ]
    page = remaining[:limit]
    next_cursor = (
        _encode_cursor(page[-1].updated_at, page[-1].run_id)
        if page and len(remaining) > limit
        else None
    )

    return ProjectMission(
        project_id=project_id,
        generated_at=now,
        window_hours=window_hours,
        runs=page,
        counts=counts,
        next_cursor=next_cursor,
        truncated=next_cursor is not None,
    )
