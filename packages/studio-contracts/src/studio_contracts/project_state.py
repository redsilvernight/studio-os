from __future__ import annotations

from datetime import datetime
from uuid import UUID

from studio_contracts.claims import ResourceClaim
from studio_contracts.common import ContractModel
from studio_contracts.tasks import Task


class ProjectState(ContractModel):
    """GET /projects/{id}/state — the aggregate view a client bootstraps from."""

    project_id: UUID
    active_tasks: list[Task]
    active_claims: list[ResourceClaim]
    generated_at: datetime
