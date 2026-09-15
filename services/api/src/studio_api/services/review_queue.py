from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.ai_work import AIWorkStatus
from studio_contracts.decisions import DecisionStatus
from studio_contracts.events import EventType
from studio_contracts.review_queue import (
    ReviewQueue,
    ReviewQueueAIWorkItem,
    ReviewQueueConflictItem,
    ReviewQueueDecisionItem,
    ReviewQueueItem,
)

from studio_api.services import ai_work as ai_work_service
from studio_api.services import decisions as decisions_service
from studio_api.services import events as events_service


async def get_review_queue(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    conflict_window_hours: int = 24,
) -> ReviewQueue:
    """Aggregates everything waiting on a human decision: AIWorkLog entries in
    `review_requested` (DEC-0041), `Decision`s still `proposed` (no transition
    endpoint exists for decisions — DEC-0049 keeps this review scoped to AI
    work, matching DEC-0041), and recent `resource.conflict` events. Conflicts
    have no persisted "still open" state (no Conflict table exists) — this is
    a best-effort, time-windowed signal, not a resolvable queue entry."""
    items: list[ReviewQueueItem] = []

    for work in await ai_work_service.list_ai_work(session, project_id=project_id):
        if work.status == AIWorkStatus.REVIEW_REQUESTED.value:
            items.append(
                ReviewQueueAIWorkItem(
                    id=work.id,
                    project_id=work.project_id,
                    task_id=work.task_id,
                    title=work.summary,
                    agent_id=work.agent_id,
                    requested_at=work.started_at,
                )
            )

    for decision in await decisions_service.list_decisions(session, project_id=project_id):
        if decision.status == DecisionStatus.PROPOSED.value:
            items.append(
                ReviewQueueDecisionItem(
                    id=decision.id,
                    project_id=decision.project_id,
                    task_id=decision.task_id,
                    readable_id=decision.readable_id,
                    title=decision.title,
                    proposed_by_type=decision.proposed_by_type,
                    requested_at=decision.created_at,
                )
            )

    since = datetime.now(UTC) - timedelta(hours=conflict_window_hours)
    conflict_events = await events_service.list_events(
        session,
        project_id=str(project_id) if project_id is not None else None,
        since=since,
        event_type=EventType.RESOURCE_CONFLICT,
        limit=500,
    )
    for event in conflict_events:
        resource_path = str(event.payload.get("resource_path", ""))
        items.append(
            ReviewQueueConflictItem(
                id=event.event_id,
                project_id=event.project_id,
                task_id=event.task_id,
                title=f"conflict on {resource_path}",
                resource_path=resource_path,
                requested_at=event.server_timestamp,
            )
        )

    items.sort(key=lambda item: item.requested_at, reverse=True)
    return ReviewQueue(items=items, generated_at=datetime.now(UTC))
