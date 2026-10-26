from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.services import project_context as context_service

from tests.mcp.conftest import FakeContext
from tests.mcp.test_prepare_context import Machine, _decision, _prepare, _principal, _project, _task
from tests.mcp.test_prepare_context_aiwork import HANDOFF_SUMMARY, _log


def test_generic_terms_are_removed_only_when_a_supported_specific_term_exists() -> None:
    corpus = ["studio shared"] * 6 + ["studio multipart"]
    assert context_service.focused_terms(["studio", "multipart"], corpus) == ["multipart"]
    assert context_service.focused_terms(["studio"], corpus) == ["studio"]
    assert context_service.focused_terms(["studio", "unknown"], corpus) == ["studio", "unknown"]
    assert context_service.query_terms("non multipart") == ["multipart"]


async def test_generic_task_term_does_not_fill_related_tasks(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    for index in range(6):
        await _task(db_session, principal, project, f"Studio generic {index}", "studio work")
    await _task(db_session, principal, project, "Multipart uploader", "studio implementation")
    result = await _prepare(auth_ctx, project, "studio multipart")
    assert [row["title"] for row in result["related_tasks"]] == ["Multipart uploader"]
    assert result["related_tasks"][0]["why"]["matched_terms"] == ["multipart"]
    assert result["additional_available"]["related_tasks"] == 6


async def test_accepted_relevant_decision_precedes_unapproved_proposal(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    accepted = await _decision(
        db_session, principal, project, "Multipart handling", "retry", status="accepted"
    )
    await _decision(db_session, principal, project, "Multipart retry proposal", "multipart retry")
    result = await _prepare(auth_ctx, project, "multipart retry")
    assert result["decisions"][0]["id"] == str(accepted.id)


async def test_requested_handoff_is_not_starved_by_large_related_task_descriptions(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext, agent: AgentModel
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    requested = await _task(db_session, principal, project, "Handoff requested", "work " * 1000)
    for index in range(6):
        await _task(db_session, principal, project, f"Handoff neighbor {index}", "neighbor " * 1000)
    await _log(db_session, principal, project, agent, requested.id, HANDOFF_SUMMARY)
    result = await _prepare(auth_ctx, project, "handoff", task_id=str(requested.id), max_chars=3000)
    assert result["task"]["id"] == str(requested.id)
    assert result["ai_work"][0]["why"]["reason"] == "linked_to_task"
    assert "NEXT update" in result["ai_work"][0]["summary"]
    assert sum(len(row["description"] or "") for row in result["related_tasks"]) <= 600
    assert result["limits"]["chars_used"] <= 3000
