"""P4 end-to-end against the P3 Roadmap service (Postgres required).

Skipped until the P3 lane lands `studio_api.services.roadmaps`; the module
import is guarded so the rest of the suite is unaffected before convergence.
The tests pin the exact service interface the MCP tools expect (DEC-0086):
`list_roadmaps`, `get_roadmap`, `import_roadmap`, `preview_hydration`,
`apply_hydration`, `update_step_progress`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("studio_api.services.roadmaps")

from studio_api.db.models.machine import MachineModel  # noqa: E402
from studio_api.db.models.project import ProjectModel  # noqa: E402
from studio_contracts.roadmaps import RoadmapDocument, RoadmapStatus  # noqa: E402
from studio_mcp.tools.roadmaps import (  # noqa: E402
    studio_get_roadmap,
    studio_preview_roadmap_hydration,
    studio_propose_roadmap,
)

from tests.mcp.conftest import FakeContext  # noqa: E402


def _document() -> RoadmapDocument:
    return RoadmapDocument.model_validate(
        {
            "title": "P4 integration",
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


async def test_absence_of_roadmap_is_not_an_error(
    db_session: AsyncSession, project: ProjectModel, ctx: Context
) -> None:
    result = await studio_get_roadmap(str(project.id), ctx)
    assert result["roadmaps"] == []
    assert result["active"] is None
    assert result["draft_pending"] == 0
    assert "error_code" not in result


async def test_propose_then_read_and_preview(
    db_session: AsyncSession, project: ProjectModel, ctx: Context
) -> None:
    proposed = await studio_propose_roadmap(
        str(project.id), _document(), ctx, submit=True, idempotency_key="p4-key-1"
    )
    assert proposed["status"] == RoadmapStatus.PROPOSED.value

    replay = await studio_propose_roadmap(
        str(project.id), _document(), ctx, submit=True, idempotency_key="p4-key-1"
    )
    assert replay["id"] == proposed["id"]

    listing = await studio_get_roadmap(str(project.id), ctx)
    assert [item["id"] for item in listing["roadmaps"]] == [proposed["id"]]
    assert listing["draft_pending"] == 1

    preview = await studio_preview_roadmap_hydration(proposed["id"], ctx)
    assert preview["applicable"] is False
    assert preview["not_applicable_reason"] == "roadmap_not_active"


async def test_readonly_cannot_propose(
    db_session: AsyncSession, project: ProjectModel, readonly_auth_ctx: Context
) -> None:
    result = await studio_propose_roadmap(str(project.id), _document(), readonly_auth_ctx)
    assert result["error_code"] == "forbidden"
