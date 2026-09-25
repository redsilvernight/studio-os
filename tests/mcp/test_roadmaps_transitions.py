"""MCP lifecycle transitions (studio_transition_roadmap).

Thin MCP layer over the same P3 service the HTTP route uses: same closed
table (`ROADMAP_TRANSITIONS`), same authority rule, same structured errors.
Real Postgres through the shared MCP fixtures.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import roadmaps as roadmaps_service
from studio_api.services.authz import load_principal
from studio_contracts.roadmaps import (
    RoadmapDocument,
    RoadmapImport,
    RoadmapTransition,
    TransitionRequest,
)

pytest.importorskip("studio_api.services.roadmaps")

from studio_mcp.tools.roadmaps import studio_transition_roadmap  # noqa: E402

from tests.mcp.conftest import FakeContext  # noqa: E402


def _document(title: str = "MCP transitions") -> RoadmapDocument:
    return RoadmapDocument.model_validate(
        {
            "title": title,
            "phases": [
                {
                    "key": "P0",
                    "title": "Phase",
                    "steps": [{"key": "P0.1", "title": "Une etape"}],
                }
            ],
        }
    )


@pytest_asyncio.fixture
async def ctx(machine: tuple[MachineModel, str]) -> AsyncIterator[FakeContext]:
    _, token = machine
    yield FakeContext(headers={"authorization": f"Bearer {token}"})


async def _draft(
    session: AsyncSession, machine: tuple[MachineModel, str], project: ProjectModel
):
    machine_model, _ = machine
    principal = await load_principal(session, machine_model)
    return await roadmaps_service.import_roadmap(
        session, principal, RoadmapImport(project_id=project.id, document=_document())
    )


async def test_transition_success_submit_then_approve(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str], ctx: Context
) -> None:
    draft = await _draft(db_session, machine, project)
    assert draft.status.value == "draft"

    submitted = await studio_transition_roadmap(
        str(draft.id), "submit", draft.version, ctx, idempotency_key="trans-ok-1"
    )
    assert submitted["status"] == "proposed"

    replay = await studio_transition_roadmap(
        str(draft.id), "submit", draft.version, ctx, idempotency_key="trans-ok-1"
    )
    assert replay["id"] == submitted["id"]
    assert replay["status"] == "proposed"

    approved = await studio_transition_roadmap(
        str(draft.id), "approve", submitted["version"], ctx
    )
    assert approved["status"] == "active"
    assert approved["version"] == submitted["version"] + 1


async def test_reopen_without_comment_is_refused(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str], ctx: Context
) -> None:
    machine_model, _ = machine
    principal = await load_principal(db_session, machine_model)
    draft = await _draft(db_session, machine, project)
    active = await roadmaps_service.transition_roadmap(
        db_session,
        principal,
        draft.id,
        TransitionRequest(transition=RoadmapTransition.ACTIVATE, expected_version=draft.version),
    )
    completed = await roadmaps_service.transition_roadmap(
        db_session,
        principal,
        draft.id,
        TransitionRequest(transition=RoadmapTransition.COMPLETE, expected_version=active.version),
    )
    assert completed.status.value == "completed"

    result = await studio_transition_roadmap(str(draft.id), "reopen", completed.version, ctx)
    assert result["error_code"] == "invalid_argument"


async def test_second_activation_conflicts_with_active_roadmap(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str], ctx: Context
) -> None:
    machine_model, _ = machine
    principal = await load_principal(db_session, machine_model)
    first = await _draft(db_session, machine, project)
    await roadmaps_service.transition_roadmap(
        db_session,
        principal,
        first.id,
        TransitionRequest(transition=RoadmapTransition.ACTIVATE, expected_version=first.version),
    )
    second = await roadmaps_service.import_roadmap(
        db_session,
        principal,
        RoadmapImport(project_id=project.id, document=_document("Second")),
    )
    submitted = await roadmaps_service.transition_roadmap(
        db_session,
        principal,
        second.id,
        TransitionRequest(transition=RoadmapTransition.SUBMIT, expected_version=second.version),
    )
    assert submitted.status.value == "proposed"

    result = await studio_transition_roadmap(
        str(second.id), "approve", submitted.version, ctx
    )
    assert result["error_code"] == "active_roadmap_exists"


async def test_readonly_role_is_refused(
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    readonly_auth_ctx: Context,
) -> None:
    draft = await _draft(db_session, machine, project)
    result = await studio_transition_roadmap(
        str(draft.id), "archive", draft.version, readonly_auth_ctx
    )
    assert result["error_code"] == "forbidden"


async def test_stale_version_conflicts_with_server_version(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str], ctx: Context
) -> None:
    draft = await _draft(db_session, machine, project)
    result = await studio_transition_roadmap(str(draft.id), "submit", draft.version + 99, ctx)
    assert result["error_code"] == "version_conflict"
    assert result["server_version"] == draft.version


async def test_unknown_transition_is_refused(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str], ctx: Context
) -> None:
    draft = await _draft(db_session, machine, project)
    result = await studio_transition_roadmap(str(draft.id), "bogus", draft.version, ctx)
    assert result["error_code"] == "invalid_argument"
