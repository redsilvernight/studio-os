"""Expected Roadmap service interface (Roadmaps P4/P5, DEC-0087).

The MCP surface (P4) and project initialization (P5) call the Roadmap domain
through this typed port. P3 owns the implementation
(`studio_api.services.roadmaps`) and exposes these module-level `async`
functions — hydration and step linking are thin adapters over
`roadmap_hydration` / `roadmap_structure`, with no duplicated business logic.
This module is the frozen, typed contract between the lanes — it contains no
business logic and no database access.

Reads take no `Principal`: roadmap reads are open to any authenticated machine
(DEC-0063/DEC-0084 §2.1). Writes take `Principal` so the service derives
provenance and applies `ensure_can_write`/`ensure_can_provision` exactly as the
HTTP routes do (DEC-0046: one service, two surfaces).

Converged: parameter names and shapes mirror the P3 runtime exactly, including
`expected_version` on progress writes (optimistic concurrency is never
negotiable) and the 404-raise (never `None`) on `get_roadmap`.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.roadmaps import (
    HydrationApplyRequest,
    HydrationRequest,
    HydrationResult,
    Roadmap,
    RoadmapImport,
    RoadmapStatus,
    RoadmapSummary,
    StepProgressUpdate,
)

from studio_api.services.authz import Principal


class RoadmapServicePort(Protocol):
    """Structural contract `studio_api.services.roadmaps` satisfies.
    Module-level functions, `session` first, `principal` on writes only."""

    async def list_roadmaps(
        self,
        session: AsyncSession,
        project_id: UUID,
        roadmap_status: RoadmapStatus | None = None,
    ) -> list[RoadmapSummary]: ...

    async def get_roadmap(self, session: AsyncSession, roadmap_id: UUID) -> Roadmap: ...

    async def import_roadmap(
        self, session: AsyncSession, principal: Principal, payload: RoadmapImport
    ) -> Roadmap: ...

    async def preview_hydration(
        self, session: AsyncSession, roadmap_id: UUID, payload: HydrationRequest
    ) -> HydrationResult: ...

    async def apply_hydration(
        self,
        session: AsyncSession,
        principal: Principal,
        roadmap_id: UUID,
        payload: HydrationApplyRequest,
    ) -> HydrationResult: ...

    async def update_step_progress(
        self,
        session: AsyncSession,
        principal: Principal,
        roadmap_id: UUID,
        step_key: str,
        payload: StepProgressUpdate,
        expected_version: int,
    ) -> Roadmap: ...

    async def link_task_by_step_key(
        self,
        session: AsyncSession,
        principal: Principal,
        roadmap_id: UUID,
        step_key: str,
        task_id: UUID,
    ) -> None: ...
