from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.ai_work import AIWorkStatus
from studio_contracts.decisions import DecisionStatus
from studio_contracts.events import EventType
from studio_contracts.review_queue import (
    ReviewQueue,
    ReviewQueueAIWorkItem,
    ReviewQueueBuildItem,
    ReviewQueueConflictItem,
    ReviewQueueDecisionItem,
    ReviewQueueItem,
    ReviewQueuePRItem,
    ReviewQueueRoadmapProposalItem,
)
from studio_contracts.roadmaps import RevisionKind, RevisionStatus, RoadmapStatus

from studio_api.db.models.roadmap import RoadmapModel, RoadmapRevisionModel
from studio_api.services import ai_work as ai_work_service
from studio_api.services import decisions as decisions_service
from studio_api.services import events as events_service
from studio_api.services import github as github_service


async def get_review_queue(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
    conflict_window_hours: int = 24,
) -> ReviewQueue:
    """Aggregates everything waiting on a human decision: AIWorkLog entries in
    `review_requested` (DEC-0041), `Decision`s still `proposed` (actionable —
    resolved via `POST /decisions/{id}/accept` or `.../supersede`, admin-only,
    DEC-0098), recent `resource.conflict` events, failed `Build`s (DEC-0059),
    and `git.pr.opened` events with no `git.pr.merged` yet (DEC-0059).
    Conflicts and PRs have no persisted "still open" state (no
    Conflict/PullRequest table exists) — these are best-effort, time-windowed
    signals, not resolvable queue entries."""
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

    for build in await github_service.list_builds(
        session, project_id=project_id, status_value="failed", limit=500
    ):
        requested_at = build.completed_at or build.updated_at
        items.append(
            ReviewQueueBuildItem(
                id=build.id,
                project_id=build.project_id,
                task_id=build.task_id,
                title=f"build failed: {build.workflow_name} #{build.run_number} on {build.branch}",
                workflow_name=build.workflow_name,
                branch=build.branch,
                commit_sha=build.commit_sha,
                conclusion=build.conclusion,
                requested_at=requested_at,
            )
        )

    opened_events = await events_service.list_events(
        session,
        project_id=str(project_id) if project_id is not None else None,
        since=since,
        event_type=EventType.GIT_PR_OPENED,
        limit=500,
    )
    merged_events = await events_service.list_events(
        session,
        project_id=str(project_id) if project_id is not None else None,
        since=since,
        event_type=EventType.GIT_PR_MERGED,
        limit=500,
    )
    merged_prs = {
        event.payload.get("pr_number")
        for event in merged_events
        if isinstance(event.payload.get("pr_number"), int)
    }
    for event in opened_events:
        pr_number = event.payload.get("pr_number")
        if not isinstance(pr_number, int) or pr_number in merged_prs:
            continue
        items.append(
            ReviewQueuePRItem(
                id=event.event_id,
                project_id=event.project_id,
                task_id=event.task_id,
                title=str(event.payload.get("title") or f"PR #{pr_number} ready"),
                pr_number=pr_number,
                head_branch=str(event.payload.get("head_branch") or ""),
                base_branch=str(event.payload.get("base_branch") or ""),
                requested_at=event.server_timestamp,
            )
        )

    roadmap_filter = [RoadmapModel.project_id == project_id] if project_id is not None else []
    proposed_roadmaps = (
        (
            await session.execute(
                select(RoadmapModel).where(
                    RoadmapModel.status == RoadmapStatus.PROPOSED.value, *roadmap_filter
                )
            )
        )
        .scalars()
        .all()
    )
    for roadmap in proposed_roadmaps:
        items.append(
            ReviewQueueRoadmapProposalItem(
                id=roadmap.id,
                project_id=roadmap.project_id,
                roadmap_id=roadmap.id,
                title=roadmap.title,
                scope="roadmap",
                status=roadmap.status,
                revision_no=roadmap.revision_no,
                actor_type=roadmap.actor_type,
                agent_id=roadmap.agent_id,
                requested_at=roadmap.updated_at,
            )
        )

    pending_revisions = (
        await session.execute(
            select(RoadmapRevisionModel, RoadmapModel)
            .join(RoadmapModel, RoadmapRevisionModel.roadmap_id == RoadmapModel.id)
            .where(
                RoadmapRevisionModel.kind == RevisionKind.PROPOSAL.value,
                RoadmapRevisionModel.status == RevisionStatus.PENDING.value,
                *roadmap_filter,
            )
        )
    ).all()
    for revision, roadmap in pending_revisions:
        items.append(
            ReviewQueueRoadmapProposalItem(
                id=revision.id,
                project_id=roadmap.project_id,
                roadmap_id=roadmap.id,
                title=roadmap.title,
                scope="revision",
                status=roadmap.status,
                revision_no=revision.revision_no,
                base_revision_no=revision.base_revision_no,
                summary=revision.summary,
                actor_type=revision.actor_type,
                agent_id=revision.agent_id,
                requested_at=revision.created_at,
            )
        )

    items.sort(key=lambda item: item.requested_at, reverse=True)
    return ReviewQueue(items=items, generated_at=datetime.now(UTC))
