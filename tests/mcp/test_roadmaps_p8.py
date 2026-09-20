"""P8 MCP surface: an agent proposes a revision on an active roadmap and reads
its status, and no MCP tool can approve its own proposal (Roadmaps P8,
DEC-0084/DEC-0087). Real Postgres through the shared MCP fixtures.
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

from studio_mcp.tools.roadmaps import studio_get_roadmap, studio_propose_roadmap  # noqa: E402

from tests.mcp.conftest import FakeContext  # noqa: E402


def _document(title: str = "MCP plan") -> RoadmapDocument:
    return RoadmapDocument.model_validate(
        {
            "title": title,
            "phases": [
                {
                    "key": "P0",
                    "title": "Phase",
                    "steps": [{"key": "P0.1", "title": "Une étape"}],
                }
            ],
        }
    )


@pytest_asyncio.fixture
async def ctx(machine: tuple[MachineModel, str]) -> AsyncIterator[FakeContext]:
    _, token = machine
    yield FakeContext(headers={"authorization": f"Bearer {token}"})


async def _active_roadmap(
    session: AsyncSession, machine: tuple[MachineModel, str], project: ProjectModel
) -> object:
    machine_model, _ = machine
    principal = await load_principal(session, machine_model)
    imported = await roadmaps_service.import_roadmap(
        session,
        principal,
        RoadmapImport(project_id=project.id, document=_document()),
    )
    return await roadmaps_service.transition_roadmap(
        session,
        principal,
        imported.id,
        TransitionRequest(transition=RoadmapTransition.ACTIVATE, expected_version=imported.version),
    )


async def test_agent_proposes_a_revision_and_reads_its_status(
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    ctx: Context,
) -> None:
    active = await _active_roadmap(db_session, machine, project)

    revision = await studio_propose_roadmap(
        str(project.id),
        _document("MCP plan v2"),
        ctx,
        roadmap_id=str(active.id),  # type: ignore[attr-defined]
        base_revision_no=active.approved_revision_no,  # type: ignore[attr-defined]
        summary="Tighten phase P0",
        idempotency_key="p8-mcp-proposal-1",
    )
    assert revision["kind"] == "proposal"
    assert revision["status"] == "pending"
    assert revision["base_revision_no"] == active.approved_revision_no  # type: ignore[attr-defined]
    assert revision["provenance"]["origin"] == "ai_proposal"

    listing = await studio_get_roadmap(str(project.id), ctx)
    assert listing["pending_proposals"] == [
        {
            "id": revision["id"],
            "roadmap_id": str(active.id),  # type: ignore[attr-defined]
            "revision_no": revision["revision_no"],
            "kind": "proposal",
            "status": "pending",
            "base_revision_no": revision["base_revision_no"],
            "summary": "Tighten phase P0",
            "provenance": revision["provenance"],
            "created_at": revision["created_at"],
            "truncated": False,
        }
    ]


async def test_proposing_a_revision_requires_a_base_revision(
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    ctx: Context,
) -> None:
    active = await _active_roadmap(db_session, machine, project)
    result = await studio_propose_roadmap(
        str(project.id),
        _document("v2"),
        ctx,
        roadmap_id=str(active.id),  # type: ignore[attr-defined]
    )
    assert result["error_code"] == "invalid_argument"


async def test_proposing_a_revision_on_an_unknown_roadmap_is_structured(
    project: ProjectModel, ctx: Context
) -> None:
    result = await studio_propose_roadmap(
        str(project.id),
        _document("v2"),
        ctx,
        roadmap_id="00000000-0000-0000-0000-000000000000",
        base_revision_no=1,
    )
    assert result["error_code"] == "not_found"
