from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from studio_contracts.budgets import (
    BudgetPolicy,
    BudgetPolicyApprove,
    BudgetPolicyUpdate,
    BudgetStatus,
)

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_BUDGET_APPROVAL,
    RESP_409_VERSION_CONFLICT,
    merge_conflict,
)
from studio_api.services import budgets as budgets_service

router = APIRouter(tags=["budgets"])


@router.get(
    "/api/v1/projects/{project_id}/budget",
    response_model=BudgetStatus,
    description=(
        "Budget status of a project over its current window: policy, effective mode, "
        "what the policy actually guarantees, meters (consumed, held, unknown entries) "
        "and recent reservations. Without a policy: alert-only, nothing limited."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_budget(
    project_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> BudgetStatus:
    return await budgets_service.get_status(session, principal, project_id)


@router.put(
    "/api/v1/projects/{project_id}/budget-policy",
    response_model=BudgetPolicy,
    description=(
        "Create (no `expected_version`) or replace the project's budget policy. An "
        "`enforce` policy is stored pending approval and stays effectively alert-only "
        "until an admin approves it; every write clears a previous approval. Refused to "
        "a launch credential."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_VERSION_CONFLICT,
    },
)
async def put_budget_policy(
    project_id: UUID,
    update: BudgetPolicyUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
) -> BudgetPolicy:
    row = await budgets_service.put_policy(session, principal, project_id, update)
    return budgets_service.to_policy(row)


@router.post(
    "/api/v1/projects/{project_id}/budget-policy/approve",
    response_model=BudgetPolicy,
    description=(
        "Approve a pending `enforce` policy (admin only). Only then can the budget "
        "refuse admissions."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **merge_conflict(RESP_409_VERSION_CONFLICT, RESP_409_BUDGET_APPROVAL),
    },
)
async def approve_budget_policy(
    project_id: UUID,
    approve: BudgetPolicyApprove,
    session: DbSession,
    principal: CurrentPrincipal,
) -> BudgetPolicy:
    row = await budgets_service.approve_policy(session, principal, project_id, approve)
    return budgets_service.to_policy(row)


@router.post(
    "/api/v1/projects/{project_id}/budget/reconcile",
    response_model=BudgetStatus,
    description=(
        "Settle the reservations of finished or overdue launches now, per the displayed "
        "policy (also done by every admission). Idempotent."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def reconcile_budget(
    project_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> BudgetStatus:
    return await budgets_service.reconcile_project(session, principal, project_id)
