"""AIB-B aggregated bootstrap plan (P2): determinism, de-duplication,
common/project segments, fail-closed. Real Postgres, no LLM."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import bootstrap_plan as plan_service
from studio_api.services import library as library_service
from studio_api.services.authz import Principal
from studio_contracts.bootstrap_plan import (
    BootstrapPlan,
    BootstrapPlanRequest,
    BootstrapSegment,
    content_hash,
)
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
)

from tests.api.test_resolution_service import (
    AGENT,
    PROFILE,
    RULE,
    SKILL,
    _agent_content,
    _create,
    _principal,
    _profile_content,
    _rule_content,
    _skill_content,
)


async def _world(db_session: AsyncSession, principal: Principal) -> None:
    await _create(db_session, principal, RULE, "plan-r1", _rule_content("Direct."))
    await _create(db_session, principal, RULE, "plan-r2", _rule_content("Transitive."))
    await _create(
        db_session,
        principal,
        SKILL,
        "plan-s1",
        _skill_content(),
        dependencies=[DependencyPin(kind=RULE, stable_key="plan-r2", version=1)],
    )
    await _create(db_session, principal, PROFILE, "plan-m", _profile_content(coding=True))
    await _create(
        db_session,
        principal,
        AGENT,
        "plan-a",
        _agent_content(),
        dependencies=[
            DependencyPin(kind=RULE, stable_key="plan-r1", version=1),
            DependencyPin(kind=SKILL, stable_key="plan-s1", version=1),
            DependencyPin(kind=PROFILE, stable_key="plan-m", version=1),
        ],
    )
    await _create(
        db_session,
        principal,
        AGENT,
        "plan-b",
        _agent_content(),
        dependencies=[DependencyPin(kind=RULE, stable_key="plan-r1", version=1)],
    )


async def test_plan_aggregates_deduplicates_and_is_deterministic(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _world(db_session, mine)
    request = BootstrapPlanRequest(project_id=project.id)

    first = await plan_service.build_bootstrap_plan(db_session, mine, request)
    second = await plan_service.build_bootstrap_plan(db_session, mine, request)

    assert first.model_dump_json() == second.model_dump_json()
    assert first.agent_keys == ["plan-a", "plan-b"]
    assert [(a.kind, a.stable_key) for a in first.artifacts] == [
        (AGENT, "plan-a"),
        (AGENT, "plan-b"),
        (PROFILE, "plan-m"),
        (SKILL, "plan-s1"),
        (RULE, "plan-r1"),
        (RULE, "plan-r2"),
    ]
    shared = next(a for a in first.artifacts if a.stable_key == "plan-r1")
    assert shared.required_by == ["plan-a", "plan-b"]
    assert shared.content_hash == content_hash(_rule_content("Direct."))
    assert shared.segment == BootstrapSegment.COMMON
    transitive = next(a for a in first.artifacts if a.stable_key == "plan-r2")
    assert transitive.paths and transitive.required_by == ["plan-a"]
    assert len(first.plan_hash) == 64


async def test_plan_hash_tracks_selection_and_ignores_key_order(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _world(db_session, mine)
    everything = await plan_service.build_bootstrap_plan(
        db_session, mine, BootstrapPlanRequest(project_id=project.id)
    )
    only_b = await plan_service.build_bootstrap_plan(
        db_session, mine, BootstrapPlanRequest(project_id=project.id, agent_keys=["plan-b"])
    )
    reordered = await plan_service.build_bootstrap_plan(
        db_session,
        mine,
        BootstrapPlanRequest(project_id=project.id, agent_keys=["plan-b", "plan-a", "plan-b"]),
    )

    assert only_b.plan_hash != everything.plan_hash
    assert [a.stable_key for a in only_b.artifacts] == ["plan-b", "plan-r1"]
    assert reordered.model_dump_json() == everything.model_dump_json()


async def test_project_scoped_resource_is_project_segment(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    resource, _ = await library_service.create_resource(
        db_session,
        mine,
        LibraryResourceCreate(
            kind=LibraryKind.AGENT_DEFINITION,
            stable_key="plan-project-agent",
            scope=LibraryScope.PROJECT,
            project_id=project.id,
            title="Project agent",
            content=_agent_content(),
        ),
    )
    await db_session.refresh(resource)
    await library_service.activate_resource_version(db_session, mine, resource, 1, resource.version)

    plan = await plan_service.build_bootstrap_plan(
        db_session, mine, BootstrapPlanRequest(project_id=project.id)
    )

    assert [(a.stable_key, a.segment) for a in plan.artifacts] == [
        ("plan-project-agent", BootstrapSegment.PROJECT)
    ]


async def test_plan_fails_closed_on_unknown_agent(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _world(db_session, mine)

    with pytest.raises(HTTPException) as exc:
        await plan_service.build_bootstrap_plan(
            db_session,
            mine,
            BootstrapPlanRequest(project_id=project.id, agent_keys=["plan-a", "nope"]),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == {"error_code": "definition_not_found"}


async def test_empty_project_yields_empty_plan(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)

    plan = await plan_service.build_bootstrap_plan(
        db_session, mine, BootstrapPlanRequest(project_id=project.id)
    )

    assert plan.artifacts == [] and plan.agent_keys == []


async def test_http_route_returns_plan(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _world(db_session, mine)

    response = await client.post(
        "/api/v1/bootstrap-plan",
        json={"project_id": str(project.id), "agent_keys": ["plan-b"]},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    plan = BootstrapPlan.model_validate(response.json())
    assert [a.stable_key for a in plan.artifacts] == ["plan-b", "plan-r1"]
    missing = await client.post(
        "/api/v1/bootstrap-plan",
        json={"project_id": str(project.id), "agent_keys": ["nope"]},
        headers=auth_headers,
    )
    assert missing.status_code == 404
