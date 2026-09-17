from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from studio_contracts.library import LibraryKind
from studio_contracts.resolution import (
    AgentResolutionRequest,
    ResolvedAgentDefinition,
)
from studio_contracts.runtime import RuntimeTarget

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_404_RUNTIME,
    RESP_422_RESOLUTION,
)
from studio_api.services import resolution as resolution_service

router = APIRouter(prefix="/api/v1/resolutions", tags=["resolutions"])


@router.post(
    "",
    response_model=ResolvedAgentDefinition,
    description=(
        "Resolve an `AgentDefinition` to its canonical "
        "`ResolvedAgentDefinition`: effective definition version, rules, "
        "skills, model profile, requirements, winning runtime, "
        "compatibility verdict and full structured provenance. Delegates "
        "to `resolve_full` — this route never re-decides anything (no "
        "fallback to another runtime on incompatibility). Optional "
        "`session_overrides` are ephemeral resolution context: validated "
        "like stored choices (unknown machine 404, another user's machine "
        "or runtime 403), winning per P4 precedence, appearing in "
        "provenance — and never persisted. Overrides naming a key outside "
        "the resolved set (agent definition + linked model profile) are "
        "ignored. Pure read: safe to retry, no "
        "`Idempotency-Key` needed."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_404_RUNTIME,
        422: RESP_422_RESOLUTION[422],
    },
)
async def resolve_agent_definition(
    resolve_in: AgentResolutionRequest,
    session: DbSession,
    principal: CurrentPrincipal,
) -> ResolvedAgentDefinition:
    overrides: dict[tuple[LibraryKind, str], RuntimeTarget] = {}
    for override in resolve_in.session_overrides:
        key = (override.target_kind, override.target_stable_key)
        if key in overrides:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error_code": "invalid_resolution_input",
                    "reason": "duplicate_session_override",
                },
            )
        overrides[key] = override.target
    return await resolution_service.resolve_full(
        session,
        principal,
        LibraryKind.AGENT_DEFINITION,
        resolve_in.stable_key,
        resolve_in.project_id,
        overrides or None,
    )
