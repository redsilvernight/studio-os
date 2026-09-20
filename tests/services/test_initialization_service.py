"""In-memory proof of the P5 reconciliation engine (no database, no P3).

The service talks to an `InitializationTarget` port; the fake target below
implements the same surface in memory, so preview/apply/permissions/idempotence
are exercised exactly as production code would drive them.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.user import UserModel
from studio_api.services.authz import Principal
from studio_api.services.initialization import (
    ResolvedResource,
    apply_initialization,
    derived_provenance,
    preview_initialization,
)
from studio_contracts.auth import Role
from studio_contracts.initialization import (
    InitializationActionKind,
    InitializationBindingRef,
    InitializationProblemCode,
    InitializationReason,
    InitializationResult,
    InitializationSection,
    InitializationTask,
    ProjectInitializationPlan,
    ProjectInitializationRequest,
)
from studio_contracts.library import LibraryKind, LibraryScope
from studio_contracts.roadmaps import PhaseContent, RoadmapDocument, StepContent, WriteProvenance
from studio_contracts.runtime import RuntimeLevel, RuntimeTarget


class FakeTarget:
    def __init__(self) -> None:
        self.projects: dict[str, UUID] = {}
        self.roadmaps: dict[UUID, dict[str, UUID]] = {}
        self.task_ids: dict[UUID, dict[str, UUID]] = {}
        self.definitions: dict[tuple[str, str, str], ResolvedResource] = {}
        self.attached: dict[UUID, set[UUID]] = {}
        self.bindings: set[tuple[str, str, str]] = set()
        self.incompatible: set[tuple[str, str]] = set()
        self.create_project_calls = 0
        self.imported_roadmaps: list[bool] = []
        self.created_tasks: list[str] = []
        self.links: list[tuple[UUID, str, UUID]] = []
        self.statuses: dict[UUID, str] = {}
        self.events: list[str] = []
        self.attached_calls: list[UUID] = []
        self.binding_calls: list[str] = []

    def add_project(self, slug: str) -> UUID:
        project_id = uuid4()
        self.projects[slug] = project_id
        self.roadmaps[project_id] = {}
        self.task_ids[project_id] = {}
        self.attached[project_id] = set()
        return project_id

    def add_resource(
        self, kind: str, stable_key: str, scope: str, version: int = 1
    ) -> ResolvedResource:
        resolved = ResolvedResource(resource_id=uuid4(), version=version)
        self.definitions[(kind, stable_key, scope)] = resolved
        return resolved

    async def project_id_for_slug(self, slug: str) -> UUID | None:
        return self.projects.get(slug)

    async def create_project(self, spec: object) -> UUID:
        self.create_project_calls += 1
        return self.add_project(spec.slug)  # type: ignore[attr-defined]

    async def roadmap_ids_by_title(self, project_id: UUID) -> dict[str, UUID]:
        return dict(self.roadmaps.get(project_id, {}))

    async def import_roadmap(
        self,
        project_id: UUID,
        document: RoadmapDocument,
        *,
        submit: bool,
        provenance: WriteProvenance,
    ) -> UUID:
        self.imported_roadmaps.append(submit)
        roadmap_id = uuid4()
        self.statuses[roadmap_id] = "proposed" if submit else "draft"
        self.roadmaps.setdefault(project_id, {})[document.title] = roadmap_id
        return roadmap_id

    async def task_ids_by_title(self, project_id: UUID) -> dict[str, UUID]:
        return dict(self.task_ids.get(project_id, {}))

    async def create_task(self, project_id: UUID, task: InitializationTask) -> UUID:
        self.created_tasks.append(task.title)
        task_id = uuid4()
        self.task_ids.setdefault(project_id, {})[task.title] = task_id
        return task_id

    async def link_task_to_step(
        self, project_id: UUID, roadmap_id: UUID, step_key: str, task_id: UUID
    ) -> None:
        # Same rule as the real service: a roadmap frozen for review (`proposed`)
        # refuses a *new* link, while an existing one is a no-op.
        if any(link == (roadmap_id, step_key, task_id) for link in self.links):
            return
        assert self.statuses[roadmap_id] == "draft", "a proposed roadmap does not accept link"
        self.events.append("link")
        self.links.append((roadmap_id, step_key, task_id))

    async def submit_roadmap(self, roadmap_id: UUID, provenance: WriteProvenance) -> None:
        if self.statuses[roadmap_id] == "draft":
            self.events.append("submit")
            self.statuses[roadmap_id] = "proposed"

    async def resolve_resource(
        self, ref: object, project_id: UUID | None
    ) -> ResolvedResource | None:
        scope = ref.scope.value if ref.scope else "studio"  # type: ignore[attr-defined]
        return self.definitions.get((ref.kind.value, ref.stable_key, scope))  # type: ignore[attr-defined]

    async def attached_resource_id(self, project_id: UUID, resource_id: UUID) -> UUID | None:
        if resource_id in self.attached.get(project_id, set()):
            return resource_id
        return None

    async def attach_resource(
        self, project_id: UUID, ref: object, resolved: ResolvedResource
    ) -> UUID | None:
        self.attached_calls.append(resolved.resource_id)
        self.attached.setdefault(project_id, set()).add(resolved.resource_id)
        return resolved.resource_id

    async def binding_problem(
        self, binding: InitializationBindingRef, project_id: UUID | None
    ) -> InitializationProblemCode | None:
        key = (binding.target_kind.value, binding.target_stable_key)
        if key not in {(k[0], k[1]) for k in self.definitions}:
            return InitializationProblemCode.BINDING_TARGET_NOT_FOUND
        if key in self.incompatible:
            return InitializationProblemCode.BINDING_INCOMPATIBLE
        return None

    async def existing_binding_id(
        self, project_id: UUID, binding: InitializationBindingRef
    ) -> UUID | None:
        key = (binding.level.value, binding.target_kind.value, binding.target_stable_key)
        if key in self.bindings:
            return uuid4()
        return None

    async def apply_binding(
        self, project_id: UUID, binding: InitializationBindingRef
    ) -> UUID | None:
        self.binding_calls.append(binding.target_stable_key)
        self.bindings.add(
            (binding.level.value, binding.target_kind.value, binding.target_stable_key)
        )
        return uuid4()


def _principal(role: str = "developer") -> Principal:
    user_id = uuid4()
    user = UserModel(id=user_id, role=role, display_name="t", email=f"{user_id}@example.test")
    machine = MachineModel(id=uuid4(), owner_user_id=user_id, display_name="m", credential_hash="x")
    return Principal(machine=machine, user=user, role=Role(role))


def _roadmap_document() -> RoadmapDocument:
    return RoadmapDocument(
        title="Plan",
        phases=[
            PhaseContent(
                key="P0",
                title="Phase",
                steps=[
                    StepContent(key="P0.1", title="Un"),
                    StepContent(key="P0.2", title="Deux", depends_on=["P0.1"]),
                ],
            )
        ],
    )


def _plan(**overrides: object) -> ProjectInitializationPlan:
    data: dict[str, object] = {"project": {"slug": "demo", "name": "Demo"}}
    data.update(overrides)
    return ProjectInitializationPlan.model_validate(data)


def _resource(**overrides: object) -> dict[str, object]:
    ref: dict[str, object] = {"kind": "skill", "stable_key": "s"}
    ref.update(overrides)
    return ref


def _binding(**overrides: object) -> dict[str, object]:
    binding: dict[str, object] = {
        "level": "project_default",
        "target_kind": "agent_definition",
        "target_stable_key": "a",
        "target": {"harness_ref": "local"},
    }
    binding.update(overrides)
    return binding


async def test_preview_of_a_new_project_without_roadmap_is_applicable() -> None:
    target = FakeTarget()
    preview = await preview_initialization(target, _plan())
    assert preview.valid and preview.applicable
    assert preview.roadmap_present is False
    assert preview.summary.created == 1
    assert preview.summary.skipped == 4
    assert [a.section for a in preview.actions] == [
        InitializationSection.PROJECT,
        InitializationSection.ROADMAP,
        InitializationSection.TASKS,
        InitializationSection.RESOURCES,
        InitializationSection.BINDINGS,
    ]
    assert preview.actions[1].reason is InitializationReason.NO_ROADMAP
    assert target.create_project_calls == 0  # preview never writes


async def test_preview_reuses_an_existing_project() -> None:
    target = FakeTarget()
    target.add_project("demo")
    preview = await preview_initialization(target, _plan())
    project = preview.actions[0]
    assert project.action is InitializationActionKind.REUSE
    assert project.reason is InitializationReason.PROJECT_ALREADY_EXISTS


async def test_missing_required_resource_blocks_and_missing_optional_skips() -> None:
    target = FakeTarget()
    blocking = await preview_initialization(target, _plan(resources=[_resource()]))
    assert not blocking.valid
    assert blocking.problems[0].code is InitializationProblemCode.RESOURCE_NOT_FOUND
    assert blocking.problems[0].blocking is True
    assert blocking.actions[3].reason is InitializationReason.RESOURCE_REQUIRED_MISSING

    optional = await preview_initialization(target, _plan(resources=[_resource(required=False)]))
    assert optional.valid and optional.applicable
    assert optional.problems[0].blocking is False
    assert optional.actions[3].reason is InitializationReason.RESOURCE_OPTIONAL_MISSING


async def test_apply_project_only_creates_it_and_reports_provenance() -> None:
    target = FakeTarget()
    result = await apply_initialization(target, _plan(), _principal())
    assert isinstance(result, InitializationResult)
    assert result.applied and target.create_project_calls == 1
    assert result.project_id == target.projects["demo"]
    assert result.provenance.actor_type == "user"
    assert result.provenance.agent_id is None


async def test_apply_full_plan_creates_every_section_and_links_tasks() -> None:
    target = FakeTarget()
    target.add_resource("skill", "s", "studio")
    target.add_resource("agent_definition", "a", "studio")
    plan = _plan(
        mode="proposed",
        roadmap=_roadmap_document(),
        tasks=[{"key": "k", "title": "Kickoff", "roadmap_step_key": "P0.1"}],
        resources=[_resource()],
        bindings=[_binding()],
    )
    result = await apply_initialization(target, plan, _principal())
    assert result.applied and result.roadmap_status == "proposed"
    # created as a draft, linked, *then* submitted: a proposed roadmap refuses links
    assert target.imported_roadmaps == [False]
    assert target.events == ["link", "submit"]
    assert set(target.statuses.values()) == {"proposed"}
    assert target.created_tasks == ["Kickoff"]
    assert len(target.links) == 1 and target.links[0][1] == "P0.1"
    assert len(target.attached_calls) == 1
    assert target.binding_calls == ["a"]
    assert result.summary.created == 5


async def test_replaying_apply_without_a_key_reuses_everything() -> None:
    target = FakeTarget()
    target.add_resource("skill", "s", "studio")
    target.add_resource("agent_definition", "a", "studio")
    plan = _plan(
        roadmap=_roadmap_document(),
        tasks=[{"key": "k", "title": "Kickoff"}],
        resources=[_resource()],
        bindings=[_binding()],
    )
    first = await apply_initialization(target, plan, _principal())
    assert first.summary.created == 5
    second = await apply_initialization(target, plan, _principal())
    assert second.summary.created == 0
    assert second.summary.reused == 5
    assert second.summary.skipped == 0
    assert target.create_project_calls == 1
    assert target.created_tasks == ["Kickoff"]
    assert len(target.imported_roadmaps) == 1


async def test_replay_repairs_a_link_lost_by_a_partial_apply() -> None:
    target = FakeTarget()
    plan = _plan(
        roadmap=_roadmap_document(),
        tasks=[{"key": "k", "title": "Kickoff", "roadmap_step_key": "P0.1"}],
    )
    first = await apply_initialization(target, plan, _principal())
    assert first.summary.created >= 1
    assert len(target.links) == 1
    target.links.clear()
    second = await apply_initialization(target, plan, _principal())
    assert second.summary.created == 0
    assert len(target.links) == 1


async def test_replaying_a_proposed_plan_never_relinks_a_frozen_roadmap() -> None:
    target = FakeTarget()
    plan = _plan(
        mode="proposed",
        roadmap=_roadmap_document(),
        tasks=[{"key": "k", "title": "Kickoff", "roadmap_step_key": "P0.1"}],
    )
    await apply_initialization(target, plan, _principal())
    second = await apply_initialization(target, plan, _principal())
    assert second.summary.created == 0
    assert target.events == ["link", "submit"]  # neither re-linked nor re-submitted
    assert len(target.imported_roadmaps) == 1


async def test_replay_completes_the_submission_an_interrupted_apply_left_as_draft() -> None:
    target = FakeTarget()
    plan = _plan(
        mode="proposed",
        roadmap=_roadmap_document(),
        tasks=[{"key": "k", "title": "Kickoff", "roadmap_step_key": "P0.1"}],
    )
    await apply_initialization(target, plan, _principal())
    for roadmap_id in target.statuses:  # simulate a crash between the links and the submit
        target.statuses[roadmap_id] = "draft"
    target.events.clear()
    second = await apply_initialization(target, plan, _principal())
    assert second.summary.created == 0
    assert target.events == ["submit"]  # already linked, only the submission is completed
    assert set(target.statuses.values()) == {"proposed"}


async def test_binding_incompatibility_blocks_apply() -> None:
    target = FakeTarget()
    target.add_resource("agent_definition", "a", "studio")
    target.incompatible.add(("agent_definition", "a"))
    preview = await preview_initialization(target, _plan(bindings=[_binding()]))
    assert not preview.valid
    assert preview.problems[0].code is InitializationProblemCode.BINDING_INCOMPATIBLE
    with pytest.raises(HTTPException) as caught:
        await apply_initialization(target, _plan(bindings=[_binding()]), _principal())
    assert caught.value.status_code == 422
    assert caught.value.detail["error_code"] == "invalid_initialization"
    assert target.binding_calls == []


async def test_readonly_cannot_apply() -> None:
    target = FakeTarget()
    target.add_project("demo")
    with pytest.raises(HTTPException) as caught:
        await apply_initialization(target, _plan(), _principal("readonly"))
    assert caught.value.status_code == 403


async def test_agent_cannot_create_a_project_but_may_initialize_into_one() -> None:
    target = FakeTarget()
    with pytest.raises(HTTPException) as caught:
        await apply_initialization(target, _plan(), _principal("agent"))
    assert caught.value.status_code == 403

    target.add_project("demo")
    result = await apply_initialization(
        target, _plan(tasks=[{"key": "k", "title": "K"}]), _principal("agent")
    )
    assert result.applied and result.provenance.actor_type == "user"


async def test_declared_agent_id_drives_agent_provenance() -> None:
    agent_id = uuid4()
    principal = _principal("agent")
    provenance = derived_provenance(principal, WriteProvenance(agent_id=agent_id))
    assert provenance.actor_type == "agent"
    assert provenance.actor_id == agent_id
    assert provenance.machine_id == principal.machine.id


async def test_apply_refuses_partial_plan_before_any_write() -> None:
    target = FakeTarget()
    target.add_resource("skill", "s", "studio")
    plan = _plan(
        resources=[_resource(), _resource(stable_key="missing")],
        tasks=[{"key": "k", "title": "K"}],
    )
    with pytest.raises(HTTPException) as caught:
        await apply_initialization(target, plan, _principal())
    assert caught.value.status_code == 422
    problems = caught.value.detail["problems"]
    assert [p["code"] for p in problems] == ["resource_not_found"]
    assert target.create_project_calls == 0
    assert target.created_tasks == []


async def test_optional_missing_resource_applies_the_rest_and_reports_a_skip() -> None:
    target = FakeTarget()
    plan = _plan(
        tasks=[{"key": "k", "title": "K"}],
        resources=[_resource(stable_key="absent", required=False)],
    )
    result = await apply_initialization(target, plan, _principal())
    assert result.applied
    assert target.created_tasks == ["K"]
    assert result.summary.skipped >= 1
    assert [p.blocking for p in result.problems] == [False]


def test_request_wraps_plan_for_the_apply_endpoint() -> None:
    request = ProjectInitializationRequest(plan=_plan())
    assert request.plan.project.slug == "demo"


def test_binding_target_and_level_types_are_reused_from_existing_contracts() -> None:
    binding = InitializationBindingRef(
        level=RuntimeLevel.STUDIO_DEFAULT,
        target_kind=LibraryKind.RULE,
        target_stable_key="r",
        target=RuntimeTarget(harness_ref="local"),
    )
    assert binding.target.harness_ref == "local"
    assert LibraryScope.STUDIO.value == "studio"
