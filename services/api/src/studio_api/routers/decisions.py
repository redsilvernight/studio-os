from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from studio_contracts.decisions import Decision, DecisionCreate

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.services import decisions as decisions_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])


@router.get("", response_model=list[Decision])
async def list_decisions(
    session: DbSession, machine: CurrentMachine, project_id: UUID | None = Query(default=None)
) -> list[Decision]:
    decisions = await decisions_service.list_decisions(session, project_id=project_id)
    return [Decision.model_validate(d) for d in decisions]


@router.post("", response_model=Decision, status_code=status.HTTP_201_CREATED)
async def create_decision(
    decision_in: DecisionCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Decision:
    """Runs unconditionally, ahead of `run_idempotent`'s replay
    short-circuit — see `routers/tasks.py::create_task` for why (DEC-0036)."""
    ensure_can_write(principal, "decision")

    async def _create() -> Decision:
        return Decision.model_validate(
            await decisions_service.create_decision(session, principal, decision_in)
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /decisions",
        Decision,
        _create,
        status.HTTP_201_CREATED,
    )
