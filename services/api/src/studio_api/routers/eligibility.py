from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from studio_contracts.auth import CapabilityToken, EligibleMachines

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN, RESP_404_NOT_FOUND
from studio_api.services import eligibility as eligibility_service
from studio_api.services import tasks as tasks_service
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1/tasks", tags=["machines"])


@router.get(
    "/{task_id}/eligible-machines",
    response_model=EligibleMachines,
    description=(
        "Machines able to receive a launch for this task (AIB R1): the "
        "caller's own User's machines, every machine for `admin`. A machine "
        "is eligible when it is online, its latest capability report is "
        "fresh, its owner can access the task's project, the project is "
        "registered on it, it accepts launches, it has the requested "
        "`harness_id` (any detected harness when omitted) and a free slot. "
        "Every ineligible machine lists all its `reasons`, evaluated in a "
        "fixed order. Eligible machines come first, then by name."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_eligible_machines(
    task_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    harness_id: CapabilityToken | None = Query(default=None),
) -> EligibleMachines:
    task = await tasks_service.read_task(session, principal, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    machines = await eligibility_service.eligible_machines(
        session,
        principal,
        project_id=task.project_id,
        harness_id=harness_id,
        settings=get_settings(),
    )
    return EligibleMachines(
        task_id=task.id, project_id=task.project_id, harness_id=harness_id, machines=machines
    )
