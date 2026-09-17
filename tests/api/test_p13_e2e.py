"""P13 — acceptance E2E du sous-système Library / Runtime / Resolution.

Une fixture canonique agnostique (définitions Studio partagées + deux
utilisateurs réels avec leurs runtimes privés) est pilotée via la surface
HTTP canonique. P13 ne rejoue pas les tests unitaires P1→P12 : il prouve les
parcours complets et les interactions entre sous-systèmes (scopes, héritage,
locks, dépendances, precedence runtime, compatibilité, isolation, auth,
idempotence, audit, déterminisme, neutralité de cœur).

Aucune fonctionnalité produit n'est ajoutée ici.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.event import EventModel
from studio_api.db.models.library import (
    LibraryResourceLinkModel,
    LibraryResourceModel,
    LibraryResourceVersionModel,
)
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import library as library_service
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services import runtime_bindings as bindings_service
from studio_api.services import runtime_registry as registry_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersionCreate,
    RuntimeCapabilities,
)
from studio_contracts.runtime import (
    RuntimeBindingCreate,
    RuntimeLevel,
    RuntimeRegistrationCreate,
    RuntimeTarget,
)

AGENT = LibraryKind.AGENT_DEFINITION
RULE = LibraryKind.RULE
SKILL = LibraryKind.SKILL
PROFILE = LibraryKind.MODEL_PROFILE
WORKFLOW = LibraryKind.WORKFLOW


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def p13_admin(
    db_session: AsyncSession,
) -> tuple[Principal, dict[str, str]]:
    """A real provisioning-capable user, distinct from the two developers:
    shared Studio definitions are authored by an authority, not by a
    beneficiary, so User A/User B ownership is unambiguous."""
    user = await provisioning_service.create_user(
        db_session, "P13 Admin", f"{uuid.uuid4()}@example.test", "admin"
    )
    machine, token = await provisioning_service.create_machine(
        db_session, user.id, "p13-admin-machine"
    )
    principal = await load_principal(db_session, machine)
    return principal, {"Authorization": f"Bearer {token}"}


async def _principal(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> Principal:
    return await load_principal(db_session, machine[0])


def _agent_content(summary: str = "Review agent.") -> dict[str, object]:
    return {"content_schema": "studio.library.agent_definition/v1", "summary": summary}


def _rule_content(text: str) -> dict[str, object]:
    return {"content_schema": "studio.library.rule/v1", "text": text}


def _skill_content(text: str) -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": text}


def _profile_content(**requirements: object) -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": dict(requirements),
        "description": "Shared requirements.",
    }


async def _create(
    db_session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    key: str,
    content: dict[str, object],
    *,
    dependencies: list[DependencyPin] | None = None,
    scope: LibraryScope = LibraryScope.STUDIO,
    project_id: UUID | None = None,
    activate: bool = True,
):
    resource, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=kind,
            stable_key=key,
            scope=scope,
            project_id=project_id,
            title=f"{key} title",
            content=content,
            dependencies=dependencies or [],
        ),
    )
    await db_session.refresh(resource)
    if activate:
        await library_service.activate_resource_version(
            db_session, principal, resource, 1, resource.version
        )
        await db_session.refresh(resource)
    return resource


async def _add_version(
    db_session: AsyncSession,
    principal: Principal,
    resource: Any,
    content: dict[str, object],
    *,
    dependencies: list[DependencyPin] | None = None,
    activate: bool = True,
):
    row = await library_service.create_resource_version(
        db_session,
        principal,
        resource,
        LibraryVersionCreate(
            title=f"{resource.stable_key} update",
            content=content,
            dependencies=dependencies or [],
        ),
    )
    await db_session.refresh(resource)
    if activate:
        await library_service.activate_resource_version(
            db_session, principal, resource, row.version, resource.version
        )
        await db_session.refresh(resource)
    return row


async def _bind(
    db_session: AsyncSession,
    principal: Principal,
    level: RuntimeLevel,
    kind: LibraryKind,
    key: str,
    target: RuntimeTarget,
    *,
    project_id: UUID | None = None,
):
    return await bindings_service.create_binding(
        db_session,
        principal,
        RuntimeBindingCreate(
            level=level,
            project_id=project_id,
            target_kind=kind,
            target_stable_key=key,
            target=target,
        ),
    )


async def _drop_binding(
    db_session: AsyncSession,
    principal: Principal,
    level: RuntimeLevel,
    kind: LibraryKind,
    key: str,
    *,
    project_id: UUID | None = None,
) -> None:
    rows = await bindings_service.list_bindings(
        db_session, principal, level=level, project_id=project_id, kind=kind, stable_key=key
    )
    assert len(rows) == 1
    await bindings_service.delete_binding(db_session, principal, rows[0])


async def _version_row(
    db_session: AsyncSession, resource_id: UUID, version: int
) -> LibraryResourceVersionModel:
    row = (
        await db_session.execute(
            select(LibraryResourceVersionModel).where(
                LibraryResourceVersionModel.resource_id == resource_id,
                LibraryResourceVersionModel.version == version,
            )
        )
    ).scalar_one()
    return row


async def _resolve(
    client: AsyncClient,
    headers: dict[str, str],
    stable_key: str,
    *,
    project_id: UUID | None = None,
    overrides: list[dict[str, Any]] | None = None,
):
    body: dict[str, Any] = {"stable_key": stable_key}
    if project_id is not None:
        body["project_id"] = str(project_id)
    if overrides is not None:
        body["session_overrides"] = overrides
    return await client.post("/api/v1/resolutions", json=body, headers=headers)


def _override(
    key: str,
    target: dict[str, Any],
    *,
    kind: str = "agent_definition",
) -> dict[str, Any]:
    return {"target_kind": kind, "target_stable_key": key, "target": target}


async def _logical_view(resolved: dict[str, Any]) -> dict[str, Any]:
    """The part of a resolution that must be identical for two users sharing
    the same canonical definitions — everything except the runtime choice."""
    return {k: v for k, v in resolved.items() if k != "runtime"}


async def _agnostic_world(
    db_session: AsyncSession,
    admin: Principal,
    owner_a: Principal,
    machine_a: UUID,
    owner_b: Principal,
    machine_b: UUID,
) -> dict[str, Any]:
    """Shared Studio definitions consumed identically by two distinct users,
    each with its own private runtime. Open, vendor-neutral refs only."""
    await _create(db_session, admin, RULE, "coding-standard", _rule_content("Coding standard."))
    await _create(db_session, admin, RULE, "security-rule", _rule_content("Security rule."))
    await _create(
        db_session,
        admin,
        SKILL,
        "code-review",
        _skill_content("Code review skill."),
        dependencies=[DependencyPin(kind=RULE, stable_key="security-rule", version=1)],
    )
    await _create(
        db_session,
        admin,
        PROFILE,
        "review-profile",
        _profile_content(coding=True),
    )
    await _create(
        db_session,
        admin,
        AGENT,
        "review-agent",
        _agent_content(),
        dependencies=[
            DependencyPin(kind=RULE, stable_key="coding-standard", version=1),
            DependencyPin(kind=SKILL, stable_key="code-review", version=1),
            DependencyPin(kind=PROFILE, stable_key="review-profile", version=1),
        ],
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.USER,
        AGENT,
        "review-agent",
        RuntimeTarget(
            machine_id=machine_a,
            harness_ref="harness_a",
            provider_ref="provider_a",
            model_ref="model_a",
            capabilities=RuntimeCapabilities(coding=True),
        ),
    )
    await _bind(
        db_session,
        owner_b,
        RuntimeLevel.USER,
        AGENT,
        "review-agent",
        RuntimeTarget(
            machine_id=machine_b,
            harness_ref="harness_b",
            provider_ref="provider_b",
            model_ref="model_b",
            capabilities=RuntimeCapabilities(coding=True),
        ),
    )
    return {"agent": "review-agent"}


# ---------------------------------------------------------------------------
# §70/§94 — Fixture agnostique : même définition logique, runtimes différents
# ---------------------------------------------------------------------------


async def test_p13_agnostic_two_users_share_logical_definition(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    owner_b = await _principal(db_session, other_machine)
    await _agnostic_world(db_session, admin, owner_a, machine[0].id, owner_b, other_machine[0].id)

    response_a = await _resolve(client, auth_headers, "review-agent")
    response_b = await _resolve(client, other_auth_headers, "review-agent")
    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text

    a = response_a.json()
    b = response_b.json()

    assert a["agent"]["stable_key"] == b["agent"]["stable_key"] == "review-agent"
    assert {r["stable_key"] for r in a["rules"]} == {"coding-standard", "security-rule"}
    assert [s["stable_key"] for s in a["skills"]] == ["code-review"]
    assert a["model_profile"]["stable_key"] == "review-profile"
    assert a["requirements"]["coding"] is True

    assert await _logical_view(a) == await _logical_view(b)

    assert a["runtime"]["target"]["provider_ref"] == "provider_a"
    assert a["runtime"]["target"]["harness_ref"] == "harness_a"
    assert a["runtime"]["target"]["model_ref"] == "model_a"
    assert b["runtime"]["target"]["provider_ref"] == "provider_b"
    assert b["runtime"]["target"]["harness_ref"] == "harness_b"
    assert b["runtime"]["target"]["model_ref"] == "model_b"
    assert a["runtime"]["level"] == b["runtime"]["level"] == "user"
    assert a["runtime"]["provenance"]["source"] == "runtime_binding"


async def test_p13_shared_definition_is_not_duplicated_per_provider(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    owner_b = await _principal(db_session, other_machine)
    await _agnostic_world(db_session, admin, owner_a, machine[0].id, owner_b, other_machine[0].id)

    rows = await library_service.list_resources(db_session, owner_a, kind="agent_definition")
    assert [r.stable_key for r in rows] == ["review-agent"]
    rules = await library_service.list_resources(db_session, owner_a, kind="rule")
    assert {r.stable_key for r in rules} == {"coding-standard", "security-rule"}
    skills = await library_service.list_resources(db_session, owner_a, kind="skill")
    assert [r.stable_key for r in skills] == ["code-review"]
    profiles = await library_service.list_resources(db_session, owner_a, kind="model_profile")
    assert [r.stable_key for r in profiles] == ["review-profile"]


# ---------------------------------------------------------------------------
# §7/§8 — Scopes, héritage, shadowing
# ---------------------------------------------------------------------------


async def test_p13_scope_shadowing_user_over_project_over_studio(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    project: ProjectModel,
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    await _create(
        db_session,
        admin,
        AGENT,
        "shadow-agent",
        _agent_content("studio"),
    )
    await _create(
        db_session,
        owner_a,
        AGENT,
        "shadow-agent",
        _agent_content("project"),
        scope=LibraryScope.PROJECT,
        project_id=project.id,
    )
    await _create(
        db_session,
        owner_a,
        AGENT,
        "shadow-agent",
        _agent_content("user"),
        scope=LibraryScope.USER,
    )

    studio_a = (await _resolve(client, auth_headers, "shadow-agent")).json()
    assert studio_a["agent"]["scope"] == "user"
    assert studio_a["agent"]["content"]["summary"] == "user"

    in_project_a = (
        await _resolve(client, auth_headers, "shadow-agent", project_id=project.id)
    ).json()
    assert in_project_a["agent"]["scope"] == "user"

    studio_b = (await _resolve(client, other_auth_headers, "shadow-agent")).json()
    assert studio_b["agent"]["scope"] == "studio"
    assert studio_b["agent"]["content"]["summary"] == "studio"

    project_b = (
        await _resolve(client, other_auth_headers, "shadow-agent", project_id=project.id)
    ).json()
    assert project_b["agent"]["scope"] == "project"
    assert project_b["agent"]["content"]["summary"] == "project"


async def test_p13_no_cross_project_shadowing(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    project_two = await projects_service.create_project(
        db_session, f"p13-{uuid.uuid4().hex[:8]}", "P13 Second Project", None
    )
    await _create(db_session, admin, AGENT, "iso-shadow", _agent_content("studio"))
    await _create(
        db_session,
        owner_a,
        AGENT,
        "iso-shadow",
        _agent_content("project-one"),
        scope=LibraryScope.PROJECT,
        project_id=project_two.id,
    )

    other_project = await projects_service.create_project(
        db_session, f"p13-{uuid.uuid4().hex[:8]}", "P13 Other Project", None
    )
    resolved = (
        await _resolve(client, auth_headers, "iso-shadow", project_id=other_project.id)
    ).json()
    assert resolved["agent"]["scope"] == "studio"


# ---------------------------------------------------------------------------
# §14/§15/§62 — Locks projet et changement de version active
# ---------------------------------------------------------------------------


async def test_p13_project_lock_pins_version_and_survives_activation(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    project: ProjectModel,
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    agent = await _create(db_session, admin, AGENT, "lock-a", _agent_content("v1"))
    await _add_version(db_session, admin, agent, _agent_content("v2"))
    await _add_version(db_session, admin, agent, _agent_content("v3"))
    assert agent.active_version == 3

    outside_before = (await _resolve(client, auth_headers, "lock-a")).json()
    assert outside_before["agent"]["version"] == 3
    assert outside_before["agent"]["version_origin"] == "active"

    from studio_contracts.library import LibraryLockCreate

    await library_service.set_lock(
        db_session,
        owner_a,
        LibraryLockCreate(project_id=project.id, resource_id=agent.id, locked_version=2),
    )

    locked = (await _resolve(client, auth_headers, "lock-a", project_id=project.id)).json()
    assert locked["agent"]["version"] == 2
    assert locked["agent"]["version_origin"] == "lock"
    assert locked["agent"]["provenance"]["locked"] is True
    assert locked["agent"]["provenance"]["source"] == "project_lock"
    assert locked["agent"]["content"]["summary"] == "v2"

    await _add_version(db_session, admin, agent, _agent_content("v4"))
    assert agent.active_version == 4

    still_locked = (await _resolve(client, auth_headers, "lock-a", project_id=project.id)).json()
    assert still_locked["agent"]["version"] == 2
    assert still_locked["agent"]["content"]["summary"] == "v2"

    outside_after = (await _resolve(client, auth_headers, "lock-a")).json()
    assert outside_after["agent"]["version"] == 4


# ---------------------------------------------------------------------------
# §11/§12/§13 — Dépendances, expansion, déduplication, préservation
# ---------------------------------------------------------------------------


async def test_p13_expansion_direct_and_transitive_with_dedup(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    await _create(db_session, admin, RULE, "dep-rule-a", _rule_content("Rule A."))
    await _create(db_session, admin, RULE, "dep-rule-b", _rule_content("Rule B."))
    await _create(
        db_session,
        admin,
        SKILL,
        "dep-skill",
        _skill_content("Skill."),
        dependencies=[
            DependencyPin(kind=RULE, stable_key="dep-rule-b", version=1),
            DependencyPin(kind=RULE, stable_key="dep-rule-a", version=1),
        ],
    )
    await _create(
        db_session,
        admin,
        AGENT,
        "dep-agent",
        _agent_content(),
        dependencies=[
            DependencyPin(kind=RULE, stable_key="dep-rule-a", version=1),
            DependencyPin(kind=SKILL, stable_key="dep-skill", version=1),
        ],
    )

    resolved = (await _resolve(client, auth_headers, "dep-agent")).json()
    rules = {r["stable_key"]: r for r in resolved["rules"]}
    assert set(rules) == {"dep-rule-a", "dep-rule-b"}
    assert {r["version"] for r in rules.values()} == {1}
    assert {r["version_origin"] for r in rules.values()} == {"pin"}

    paths_a = rules["dep-rule-a"]["paths"]
    assert len(paths_a) == 2
    assert {p["relation"] for p in paths_a} == {"applies_rule", "refines_skill_rule"}
    assert {p["via_stable_key"] for p in paths_a} == {"dep-agent", "dep-skill"}
    assert len(rules["dep-rule-b"]["paths"]) == 1
    assert rules["dep-rule-b"]["paths"][0]["via_stable_key"] == "dep-skill"

    assert resolved["skills"][0]["stable_key"] == "dep-skill"
    assert resolved["skills"][0]["version_origin"] == "pin"


async def test_p13_composed_agent_and_workflow_preserved_not_expanded(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    await _create(db_session, admin, AGENT, "pres-child", _agent_content("child"))
    await _create(
        db_session,
        admin,
        WORKFLOW,
        "pres-flow",
        {
            "content_schema": "studio.library.workflow/v1",
            "participants": [
                {
                    "participant_id": "worker",
                    "agent_stable_key": "pres-child",
                }
            ],
        },
        dependencies=[DependencyPin(kind=AGENT, stable_key="pres-child", version=1)],
    )
    await _create(
        db_session,
        admin,
        AGENT,
        "pres-root",
        _agent_content("root"),
        dependencies=[
            DependencyPin(kind=AGENT, stable_key="pres-child", version=1),
            DependencyPin(kind=WORKFLOW, stable_key="pres-flow", version=1),
        ],
    )

    resolved = (await _resolve(client, auth_headers, "pres-root")).json()
    assert [c["stable_key"] for c in resolved["composed_agents"]] == ["pres-child"]
    assert [w["stable_key"] for w in resolved["workflows"]] == ["pres-flow"]
    assert resolved["composed_agents"][0]["relation"] == "composes_agent"
    assert resolved["workflows"][0]["relation"] == "references_workflow"
    # Preserved identity, never expanded: the composed agent's own dependency
    # does not leak into the root's resolved rules.
    assert resolved["rules"] == []


# ---------------------------------------------------------------------------
# §16 — Deprecated
# ---------------------------------------------------------------------------


async def test_p13_deprecated_dependency_and_root_keep_resolving(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    rule = await _create(db_session, admin, RULE, "dep-old-rule", _rule_content("Old rule."))
    await _create(db_session, admin, PROFILE, "dep-old-profile", _profile_content(coding=True))
    agent = await _create(
        db_session,
        admin,
        AGENT,
        "dep-old-agent",
        _agent_content("Deprecated root."),
        dependencies=[
            DependencyPin(kind=RULE, stable_key="dep-old-rule", version=1),
            DependencyPin(kind=PROFILE, stable_key="dep-old-profile", version=1),
        ],
    )
    await library_service.deprecate_resource(db_session, admin, rule, rule.version)
    await db_session.refresh(rule)
    await library_service.deprecate_resource(db_session, admin, agent, agent.version)
    await db_session.refresh(agent)

    resolved = (await _resolve(client, auth_headers, "dep-old-agent")).json()
    assert resolved["agent"]["deprecated"] is True
    assert resolved["rules"][0]["deprecated"] is True
    assert resolved["model_profile"]["deprecated"] is False


# ---------------------------------------------------------------------------
# §17/§18 — Dépendance manquante / invisible (état corrompu, non oracle)
# ---------------------------------------------------------------------------


async def test_p13_missing_dependency_is_404_not_500(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    rule = await _create(db_session, admin, RULE, "miss-rule", _rule_content("Rule."))
    agent = await _create(db_session, admin, AGENT, "miss-agent", _agent_content())
    row = await _version_row(db_session, agent.id, 1)
    # Corrupted historical state the API correctly refuses to create: a pin to
    # a version that does not exist. Injected at the fixture layer only.
    db_session.add(
        LibraryResourceLinkModel(
            from_version_id=row.id,
            to_resource_id=rule.id,
            to_version=99,
            relation="applies_rule",
        )
    )
    await db_session.flush()
    before_active = agent.active_version

    response = await _resolve(client, auth_headers, "miss-agent")
    assert response.status_code == 404
    assert response.json()["detail"] == {"error_code": "definition_not_found"}
    assert response.status_code != 500

    await db_session.refresh(agent)
    assert agent.active_version == before_active


async def test_p13_invisible_dependency_stays_masked_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_b = await _principal(db_session, other_machine)
    private_rule = await _create(
        db_session,
        owner_b,
        RULE,
        "invis-rule",
        _rule_content("Private."),
        scope=LibraryScope.USER,
    )
    agent = await _create(db_session, admin, AGENT, "invis-agent", _agent_content())
    row = await _version_row(db_session, agent.id, 1)
    db_session.add(
        LibraryResourceLinkModel(
            from_version_id=row.id,
            to_resource_id=private_rule.id,
            to_version=1,
            relation="applies_rule",
        )
    )
    await db_session.flush()

    masked = await _resolve(client, auth_headers, "invis-agent")
    assert masked.status_code == 404
    body = masked.json()
    assert body["detail"] == {"error_code": "definition_not_found"}
    assert "invis-rule" not in masked.text

    visible = await _resolve(client, other_auth_headers, "invis-agent")
    assert visible.status_code == 200
    assert [r["stable_key"] for r in visible.json()["rules"]] == ["invis-rule"]

    listed = await client.get(
        "/api/v1/library", params={"kind": "rule", "scope": "user"}, headers=auth_headers
    )
    assert listed.status_code == 200
    assert "invis-rule" not in listed.text


# ---------------------------------------------------------------------------
# §9/§10 — Precedence runtime et session override
# ---------------------------------------------------------------------------


async def test_p13_runtime_precedence_ladder_http(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    project: ProjectModel,
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    await _create(db_session, admin, AGENT, "ladder-a", _agent_content())
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.STUDIO_DEFAULT,
        AGENT,
        "ladder-a",
        RuntimeTarget(model_ref="studio-default"),
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.PROJECT_DEFAULT,
        AGENT,
        "ladder-a",
        RuntimeTarget(model_ref="project-default"),
        project_id=project.id,
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.USER,
        AGENT,
        "ladder-a",
        RuntimeTarget(model_ref="user"),
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.PROJECT_OVERRIDE,
        AGENT,
        "ladder-a",
        RuntimeTarget(model_ref="project-override"),
        project_id=project.id,
    )

    project_body = {"stable_key": "ladder-a", "project_id": str(project.id)}

    def _model(response: Any) -> str:
        return response.json()["runtime"]["target"]["model_ref"]

    top = await client.post("/api/v1/resolutions", json=project_body, headers=auth_headers)
    assert _model(top) == "project-override"
    assert top.json()["runtime"]["level"] == "project_override"

    await _drop_binding(
        db_session,
        owner_a,
        RuntimeLevel.PROJECT_OVERRIDE,
        AGENT,
        "ladder-a",
        project_id=project.id,
    )
    fallback_one = await client.post("/api/v1/resolutions", json=project_body, headers=auth_headers)
    assert _model(fallback_one) == "user"
    assert fallback_one.json()["runtime"]["level"] == "user"

    await _drop_binding(db_session, owner_a, RuntimeLevel.USER, AGENT, "ladder-a")
    fallback_two = await client.post("/api/v1/resolutions", json=project_body, headers=auth_headers)
    assert _model(fallback_two) == "project-default"
    assert fallback_two.json()["runtime"]["level"] == "project_default"

    await _drop_binding(
        db_session,
        owner_a,
        RuntimeLevel.PROJECT_DEFAULT,
        AGENT,
        "ladder-a",
        project_id=project.id,
    )
    fallback_three = await client.post(
        "/api/v1/resolutions", json=project_body, headers=auth_headers
    )
    assert _model(fallback_three) == "studio-default"
    assert fallback_three.json()["runtime"]["level"] == "studio_default"

    session = await client.post(
        "/api/v1/resolutions",
        json={
            **project_body,
            "session_overrides": [_override("ladder-a", {"model_ref": "session"})],
        },
        headers=auth_headers,
    )
    assert _model(session) == "session"
    assert session.json()["runtime"]["level"] == "session"


async def test_p13_session_override_is_ephemeral_and_wins(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    await _create(db_session, admin, AGENT, "sess-a", _agent_content())
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.USER,
        AGENT,
        "sess-a",
        RuntimeTarget(machine_id=machine[0].id, model_ref="stored"),
    )
    before = len(await bindings_service.list_bindings(db_session, owner_a))

    with_override = await _resolve(
        client,
        auth_headers,
        "sess-a",
        overrides=[
            _override(
                "sess-a",
                {
                    "machine_id": str(machine[0].id),
                    "harness_ref": "harness_a",
                    "provider_ref": "provider_a",
                    "model_ref": "session-model",
                },
            )
        ],
    )
    assert with_override.status_code == 200, with_override.text
    runtime = with_override.json()["runtime"]
    assert runtime["level"] == "session"
    assert runtime["target"]["model_ref"] == "session-model"
    assert runtime["provenance"]["source"] == "session_override"

    after = len(await bindings_service.list_bindings(db_session, owner_a))
    assert after == before

    without = await _resolve(client, auth_headers, "sess-a")
    assert without.json()["runtime"]["level"] == "user"
    assert without.json()["runtime"]["target"]["model_ref"] == "stored"


# ---------------------------------------------------------------------------
# §19/§20/§21 — Compatibilité runtime
# ---------------------------------------------------------------------------


async def test_p13_incompatible_winner_has_no_fallback(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    project: ProjectModel,
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    await _create(db_session, admin, PROFILE, "inc-profile", _profile_content(coding=True))
    await _create(
        db_session,
        admin,
        AGENT,
        "inc-agent",
        _agent_content(),
        dependencies=[DependencyPin(kind=PROFILE, stable_key="inc-profile", version=1)],
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.PROJECT_OVERRIDE,
        AGENT,
        "inc-agent",
        RuntimeTarget(model_ref="weak", capabilities=RuntimeCapabilities(coding=False)),
        project_id=project.id,
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.USER,
        AGENT,
        "inc-agent",
        RuntimeTarget(model_ref="strong", capabilities=RuntimeCapabilities(coding=True)),
    )

    without_project = await _resolve(client, auth_headers, "inc-agent")
    assert without_project.status_code == 200, without_project.text
    assert without_project.json()["runtime"]["target"]["model_ref"] == "strong"

    with_project = await _resolve(client, auth_headers, "inc-agent", project_id=project.id)
    assert with_project.status_code == 422, with_project.text
    detail = with_project.json()["detail"]
    assert detail["error_code"] == "runtime_incompatible"
    assert detail["level"] == "project_override"
    assert detail["matched_stable_key"] == "inc-agent"
    assert detail["unsatisfied"] == ["coding: required"]
    assert "runtime" not in with_project.json()


async def test_p13_unknown_capability_is_not_compatible(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    await _create(
        db_session,
        admin,
        PROFILE,
        "unk-profile",
        _profile_content(reasoning="deep", tools_required=["lint"]),
    )
    await _create(
        db_session,
        admin,
        AGENT,
        "unk-agent",
        _agent_content(),
        dependencies=[DependencyPin(kind=PROFILE, stable_key="unk-profile", version=1)],
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.USER,
        AGENT,
        "unk-agent",
        RuntimeTarget(model_ref="plain"),
    )

    response = await _resolve(client, auth_headers, "unk-agent")
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "runtime_incompatible"
    assert any("reasoning" in item for item in detail["unsatisfied"])
    assert any("tools_required" in item for item in detail["unsatisfied"])


# ---------------------------------------------------------------------------
# §22/§23/§24 — Révocation runtime/machine, absence de binding
# ---------------------------------------------------------------------------


async def test_p13_revoked_runtime_binding_falls_through(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    await _create(db_session, admin, AGENT, "rvk-a", _agent_content())
    runtime = await registry_service.register_runtime(
        db_session, owner_a, RuntimeRegistrationCreate(model_ref="doomed")
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.USER,
        AGENT,
        "rvk-a",
        RuntimeTarget(runtime_id=runtime.id),
    )

    live = await _resolve(client, auth_headers, "rvk-a")
    assert live.status_code == 200, live.text
    assert live.json()["runtime"]["target"]["model_ref"] == "doomed"

    await registry_service.revoke_runtime(db_session, owner_a, runtime)

    after = await _resolve(client, auth_headers, "rvk-a")
    assert after.status_code == 200, after.text
    assert after.json()["runtime"] is None


async def test_p13_revoked_machine_makes_runtime_non_live(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    await _create(db_session, admin, AGENT, "rvm-a", _agent_content())
    locus, _ = await provisioning_service.create_machine(
        db_session, owner_a.user.id, "runtime-locus"
    )
    runtime = await registry_service.register_runtime(
        db_session,
        owner_a,
        RuntimeRegistrationCreate(machine_id=locus.id, model_ref="local"),
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.USER,
        AGENT,
        "rvm-a",
        RuntimeTarget(runtime_id=runtime.id),
    )

    live = await _resolve(client, auth_headers, "rvm-a")
    assert live.status_code == 200, live.text
    assert live.json()["runtime"] is not None

    await provisioning_service.revoke_machine(db_session, locus)

    after = await _resolve(client, auth_headers, "rvm-a")
    assert after.status_code == 200, after.text
    assert after.json()["runtime"] is None


async def test_p13_no_binding_is_a_valid_null_runtime(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    await _create(db_session, admin, AGENT, "bare-a", _agent_content())
    response = await _resolve(client, auth_headers, "bare-a")
    assert response.status_code == 200, response.text
    assert response.json()["runtime"] is None


# ---------------------------------------------------------------------------
# §25/§26 — Isolation user et projet
# ---------------------------------------------------------------------------


async def test_p13_cross_user_isolation_matrix(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_b = await _principal(db_session, other_machine)
    await _create(
        db_session, owner_b, AGENT, "priv-b", _agent_content("private"), scope=LibraryScope.USER
    )
    runtime_b = await registry_service.register_runtime(
        db_session, owner_b, RuntimeRegistrationCreate(model_ref="b-only")
    )
    binding_b = await _bind(
        db_session,
        owner_b,
        RuntimeLevel.USER,
        AGENT,
        "priv-b",
        RuntimeTarget(runtime_id=runtime_b.id),
    )

    rt = await client.get(f"/api/v1/runtimes/{runtime_b.id}", headers=auth_headers)
    assert rt.status_code == 404
    patch = await client.patch(
        f"/api/v1/runtimes/{runtime_b.id}",
        json={"update": {"model_ref": "hijack"}, "expected_version": 1},
        headers=auth_headers,
    )
    assert patch.status_code == 404
    revoke = await client.post(f"/api/v1/runtimes/{runtime_b.id}/revoke", headers=auth_headers)
    assert revoke.status_code == 404

    got = await client.get(f"/api/v1/runtime-bindings/{binding_b.id}", headers=auth_headers)
    assert got.status_code == 404
    deleted = await client.delete(f"/api/v1/runtime-bindings/{binding_b.id}", headers=auth_headers)
    assert deleted.status_code == 404

    listed = await client.get(
        "/api/v1/runtime-bindings", params={"level": "user"}, headers=auth_headers
    )
    assert listed.status_code == 200
    assert str(binding_b.id) not in listed.text

    cross_runtime = await client.post(
        "/api/v1/runtime-bindings",
        json={
            "level": "user",
            "target_kind": "agent_definition",
            "target_stable_key": "priv-b",
            "target": {"runtime_id": str(runtime_b.id)},
        },
        headers=auth_headers,
    )
    assert cross_runtime.status_code == 403

    cross_machine = await client.post(
        "/api/v1/runtime-bindings",
        json={
            "level": "user",
            "target_kind": "agent_definition",
            "target_stable_key": "priv-b",
            "target": {"machine_id": str(other_machine[0].id)},
        },
        headers=auth_headers,
    )
    assert cross_machine.status_code == 403

    private_resolution = await _resolve(client, auth_headers, "priv-b")
    assert private_resolution.status_code == 404
    assert private_resolution.json()["detail"] == {"error_code": "definition_not_found"}
    assert "b-only" not in private_resolution.text


async def test_p13_cross_project_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    project_one = await projects_service.create_project(
        db_session, f"p13-{uuid.uuid4().hex[:8]}", "P13 One", None
    )
    project_two = await projects_service.create_project(
        db_session, f"p13-{uuid.uuid4().hex[:8]}", "P13 Two", None
    )
    await _create(db_session, admin, AGENT, "proj-iso", _agent_content())
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.STUDIO_DEFAULT,
        AGENT,
        "proj-iso",
        RuntimeTarget(model_ref="studio-default"),
    )
    await _bind(
        db_session,
        owner_a,
        RuntimeLevel.PROJECT_OVERRIDE,
        AGENT,
        "proj-iso",
        RuntimeTarget(model_ref="project-one-only"),
        project_id=project_one.id,
    )

    one = await _resolve(client, auth_headers, "proj-iso", project_id=project_one.id)
    two = await _resolve(client, auth_headers, "proj-iso", project_id=project_two.id)
    assert one.json()["runtime"]["target"]["model_ref"] == "project-one-only"
    assert two.json()["runtime"]["target"]["model_ref"] == "studio-default"

    agent = await _create(db_session, admin, AGENT, "proj-lock", _agent_content("v1"))
    await _add_version(db_session, admin, agent, _agent_content("v2"))
    from studio_contracts.library import LibraryLockCreate

    await library_service.set_lock(
        db_session,
        owner_a,
        LibraryLockCreate(project_id=project_one.id, resource_id=agent.id, locked_version=1),
    )
    locked = await _resolve(client, auth_headers, "proj-lock", project_id=project_one.id)
    unlocked = await _resolve(client, auth_headers, "proj-lock", project_id=project_two.id)
    assert locked.json()["agent"]["version"] == 1
    assert unlocked.json()["agent"]["version"] == 2


# ---------------------------------------------------------------------------
# §27/§28/§29 — Permissions, auth HTTP, principal serveur
# ---------------------------------------------------------------------------


async def test_p13_permissions_matrix(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    agent = await _create(db_session, admin, AGENT, "perm-a", _agent_content())

    readonly_body = {
        "kind": "rule",
        "stable_key": f"perm-ro-{uuid.uuid4().hex[:8]}",
        "scope": "user",
        "title": "readonly attempt",
        "content": _rule_content("nope"),
    }
    assert (
        await client.post("/api/v1/library", json=readonly_body, headers=readonly_auth_headers)
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/runtime-bindings",
            json={
                "level": "user",
                "target_kind": "agent_definition",
                "target_stable_key": "perm-a",
                "target": {"model_ref": "x"},
            },
            headers=readonly_auth_headers,
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/runtimes",
            json={"model_ref": "x"},
            headers=readonly_auth_headers,
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/library-locks",
            json={
                "project_id": str(project.id),
                "resource_id": str(agent.id),
                "locked_version": 1,
            },
            headers=readonly_auth_headers,
        )
    ).status_code == 403
    assert (
        await client.get("/api/v1/library-locks", headers=readonly_auth_headers)
    ).status_code == 200

    from studio_contracts.library import LibraryLockCreate

    lock = await library_service.set_lock(
        db_session,
        owner_a,
        LibraryLockCreate(project_id=project.id, resource_id=agent.id, locked_version=1),
    )
    assert (
        await client.delete(f"/api/v1/library-locks/{lock.id}", headers=other_auth_headers)
    ).status_code == 403

    binding = await _bind(
        db_session,
        owner_a,
        RuntimeLevel.USER,
        AGENT,
        "perm-a",
        RuntimeTarget(model_ref="mine"),
    )
    assert (
        await client.delete(f"/api/v1/runtime-bindings/{binding.id}", headers=other_auth_headers)
    ).status_code == 404
    released = await client.delete(f"/api/v1/runtime-bindings/{binding.id}", headers=auth_headers)
    assert released.status_code == 200
    assert released.json()["id"] == str(binding.id)


async def test_p13_http_auth_surfaces_and_server_derived_principal(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin_principal, admin_headers = p13_admin
    del admin_principal

    assert (await client.post("/api/v1/resolutions", json={"stable_key": "x"})).status_code == 401
    invalid = await client.post(
        "/api/v1/resolutions",
        json={"stable_key": "x"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert invalid.status_code == 401
    assert (await client.get("/api/v1/library")).status_code == 401

    admin_email = f"{uuid.uuid4()}@example.test"
    user = await provisioning_service.create_user(db_session, "JWT User", admin_email, "admin")
    await provisioning_service.set_user_password(db_session, user.email, "secret123")
    login = await client.post(
        "/api/v1/auth/token", json={"email": admin_email, "password": "secret123"}
    )
    assert login.status_code == 200
    jwt_token = login.json()["access_token"]
    jwt_headers = {"Authorization": f"Bearer {jwt_token}"}
    assert (await client.get("/api/v1/library", headers=jwt_headers)).status_code == 200

    machine_probe = await client.get("/api/v1/library", headers=auth_headers)
    assert machine_probe.status_code == 200

    injected = await client.post(
        "/api/v1/library",
        json={
            "kind": "rule",
            "stable_key": f"inj-{uuid.uuid4().hex[:8]}",
            "scope": "user",
            "title": "injected owner",
            "content": _rule_content("x"),
            "owner_user_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert injected.status_code == 422

    injected_binding = await client.post(
        "/api/v1/runtime-bindings",
        json={
            "level": "user",
            "target_kind": "agent_definition",
            "target_stable_key": "x",
            "target": {"model_ref": "x"},
            "owner_user_id": str(uuid.uuid4()),
        },
        headers=admin_headers,
    )
    assert injected_binding.status_code == 422


# ---------------------------------------------------------------------------
# §34/§35 — Audit/events et idempotence HTTP
# ---------------------------------------------------------------------------


async def test_p13_audit_event_for_project_mutation(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    owner_a = await _principal(db_session, machine)
    key = f"audit-{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/api/v1/library",
        json={
            "kind": "rule",
            "stable_key": key,
            "scope": "project",
            "project_id": str(project.id),
            "title": "Audited rule",
            "content": _rule_content("audited"),
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    events = (
        (
            await db_session.execute(
                select(EventModel).where(
                    EventModel.project_id == project.id,
                    EventModel.event_type == "library.version.created",
                )
            )
        )
        .scalars()
        .all()
    )
    matching = [e for e in events if e.payload.get("stable_key") == key]
    assert len(matching) == 1
    event = matching[0]
    assert event.actor_type == "user"
    assert event.actor_id == owner_a.user.id
    assert event.machine_id == machine[0].id
    assert "authorization" not in str(event.payload).lower()
    assert "token" not in str(event.payload).lower()


async def test_p13_idempotent_library_create_replay_and_mismatch(
    client: AsyncClient,
    db_session: AsyncSession,
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    _, admin_headers = p13_admin
    key = f"idem-{uuid.uuid4().hex[:8]}"
    idem = f"p13-key-{uuid.uuid4().hex[:8]}"
    body = {
        "kind": "rule",
        "stable_key": key,
        "scope": "studio",
        "title": "Idempotent rule",
        "content": _rule_content("idempotent"),
    }

    first = await client.post(
        "/api/v1/library", json=body, headers={**admin_headers, "Idempotency-Key": idem}
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/api/v1/library", json=body, headers={**admin_headers, "Idempotency-Key": idem}
    )
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(LibraryResourceModel)
            .where(LibraryResourceModel.stable_key == key)
        )
    ).scalar_one()
    assert count == 1

    conflicting = {**body, "title": "Different payload"}
    mismatch = await client.post(
        "/api/v1/library", json=conflicting, headers={**admin_headers, "Idempotency-Key": idem}
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"


# ---------------------------------------------------------------------------
# §65 — Déterminisme
# ---------------------------------------------------------------------------


async def test_p13_resolution_is_deterministic_across_repeats(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    owner_a = await _principal(db_session, machine)
    owner_b = await _principal(db_session, other_machine)
    await _agnostic_world(db_session, admin, owner_a, machine[0].id, owner_b, other_machine[0].id)

    first = (await _resolve(client, auth_headers, "review-agent")).json()
    for _ in range(3):
        assert (await _resolve(client, auth_headers, "review-agent")).json() == first


# ---------------------------------------------------------------------------
# §49/§50/§51 — Workflow déclaratif : cycle de vie, DAG, frontière d'exécution
# ---------------------------------------------------------------------------


async def test_p13_workflow_declarative_lifecycle_and_boundary(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    p13_admin: tuple[Principal, dict[str, str]],
) -> None:
    admin, _ = p13_admin
    for agent_key in ("flow-implementer", "flow-tester", "flow-documenter", "flow-reviewer"):
        await _create(db_session, admin, AGENT, agent_key, _agent_content(agent_key))

    content = {
        "content_schema": "studio.library.workflow/v1",
        "summary": "Declarative delivery workflow.",
        "participants": [
            {"participant_id": "implementer", "agent_stable_key": "flow-implementer"},
            {
                "participant_id": "tester",
                "agent_stable_key": "flow-tester",
                "depends_on": ["implementer"],
                "inputs": [
                    {"name": "code", "source": {"participant_id": "implementer", "name": "code"}}
                ],
            },
            {
                "participant_id": "documenter",
                "agent_stable_key": "flow-documenter",
                "depends_on": ["implementer"],
            },
            {
                "participant_id": "reviewer",
                "agent_stable_key": "flow-reviewer",
                "depends_on": ["tester", "documenter"],
            },
        ],
        "outputs": [
            {
                "name": "review",
                "source": {"participant_id": "reviewer", "name": "review"},
            }
        ],
    }
    content["participants"][0]["outputs"] = [{"name": "code"}]
    content["participants"][3]["outputs"] = [{"name": "review"}]

    payload = {
        "kind": "workflow",
        "stable_key": "delivery-flow",
        "scope": "studio",
        "title": "Delivery flow",
        "content": content,
        "dependencies": [
            {"kind": "agent_definition", "stable_key": key, "version": 1}
            for key in (
                "flow-implementer",
                "flow-tester",
                "flow-documenter",
                "flow-reviewer",
            )
        ],
    }
    created = await client.post(
        "/api/v1/library",
        json=payload,
        headers={**auth_headers, "Idempotency-Key": f"p13-flow-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    resource_id = created.json()["id"]

    active = await client.post(
        f"/api/v1/library/{resource_id}/activate",
        json={"version": 1, "expected_resource_version": created.json()["version"]},
        headers=auth_headers,
    )
    assert active.status_code == 200, active.text

    detail = await client.get(f"/api/v1/library/{resource_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["kind"] == "workflow"

    serialized = str(detail.json()).lower()
    for forbidden in (
        "workflowrun",
        "workflowexecution",
        "execute_workflow",
        "next_step",
        "schedule_workflow",
    ):
        assert forbidden not in serialized

    duplicate = {
        **payload,
        "content": {**content, "summary": None},
        "stable_key": f"dup-{uuid.uuid4().hex[:8]}",
    }
    duplicate["content"]["participants"] = [
        {"participant_id": "implementer", "agent_stable_key": "flow-implementer"},
        {"participant_id": "implementer", "agent_stable_key": "flow-tester"},
    ]
    dup = await client.post(
        "/api/v1/library",
        json=duplicate,
        headers={**auth_headers, "Idempotency-Key": f"p13-dup-{uuid.uuid4().hex[:8]}"},
    )
    assert dup.status_code == 422
    assert dup.json()["detail"]["error_code"] == "invalid_workflow"
    assert dup.json()["detail"]["reason"] == "duplicate_participant"


# ---------------------------------------------------------------------------
# §69 — Neutralité de cœur (garde structurelle)
# ---------------------------------------------------------------------------


def test_p13_core_has_no_provider_model_harness_branches() -> None:
    repo = Path(__file__).resolve().parents[2]
    zones = [
        repo / "packages" / "studio-contracts" / "src",
        repo / "services" / "api" / "src" / "studio_api" / "services",
    ]
    branch = re.compile(r"(if|elif)[^\n]*\b(provider|model|harness)(_ref)?\s*==")
    vendor = (
        "claude-code",
        "claude_code",
        "opencode",
        "open_code",
        "anthropic",
        "openai",
        "gemini",
        "mistral",
        "ollama",
    )
    catalog = re.compile(r"(VENDOR|PROVIDER|MODEL|HARNESS)_(CATALOG|WHITELIST|ALLOWLIST)")

    offenders: list[str] = []
    for zone in zones:
        for path in sorted(zone.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            lowered = text.lower()
            hits = [token for token in vendor if token in lowered]
            if branch.search(text) or catalog.search(text) or hits:
                offenders.append(f"{path.relative_to(repo)}: {hits or 'branch'}")
    assert offenders == [], offenders
