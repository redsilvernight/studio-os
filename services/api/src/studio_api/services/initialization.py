"""Project initialization service (Roadmaps P5, DEC-0084/DEC-0087).

Studio OS never decides for the agent: this module takes a structured
`ProjectInitializationPlan` and *reconciles* it with the current state —
preview with no side effect, then apply idempotently. It owns no Roadmap DB
model: every write goes through the `InitializationTarget` port, whose default
adapter reuses the existing services (projects, tasks, library, runtime
bindings) and the P3 Roadmap service. Tests drive the exact same logic with an
in-memory fake target, so this lane is fully buildable before P3 lands.

The roadmap is optional: a plan with no roadmap is reconciled and applied
normally, and an empty/absent section is a `skip`, never an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol, cast
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.initialization import (
    InitializationAction,
    InitializationActionKind,
    InitializationBindingRef,
    InitializationPreview,
    InitializationProblem,
    InitializationProblemCode,
    InitializationProjectSpec,
    InitializationReason,
    InitializationResourceRef,
    InitializationResult,
    InitializationSection,
    InitializationSummary,
    InitializationTask,
    ProjectInitializationPlan,
    blocking_problems,
    count_actions,
    initialization_plan_problems,
)
from studio_contracts.library import LibraryLockCreate, LibraryResolution
from studio_contracts.roadmaps import (
    Provenance,
    RoadmapDocument,
    RoadmapImport,
    WriteProvenance,
)
from studio_contracts.runtime import RuntimeBindingCreate, RuntimeLevel
from studio_contracts.tasks import TaskCreate

from studio_api.services import library as library_service
from studio_api.services import projects as projects_service
from studio_api.services import runtime_bindings as runtime_bindings_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_provision,
    ensure_can_write,
    with_created_project,
)
from studio_api.services.roadmap_port import RoadmapServicePort

_PROJECT_LEVELS = (RuntimeLevel.PROJECT_OVERRIDE, RuntimeLevel.PROJECT_DEFAULT)


@dataclass(frozen=True)
class ResolvedResource:
    """A Library definition resolved for the caller: the canonical resource id
    and the version the plan pins (its own `version`, else the effective one)."""

    resource_id: UUID
    version: int


@dataclass
class _Recon:
    actions: list[InitializationAction] = field(default_factory=list)
    problems: list[InitializationProblem] = field(default_factory=list)
    project_id: UUID | None = None
    roadmap_id: UUID | None = None
    resolved_resources: dict[str, ResolvedResource] = field(default_factory=dict)
    create_task_keys: list[str] = field(default_factory=list)
    reused_task_ids: dict[str, UUID] = field(default_factory=dict)


class InitializationTarget(Protocol):
    """Server-state port. Read methods let preview reconcile without writing;
    write methods apply one section each. The default adapter talks to the real
    Studio OS services; a fake target implements the same surface in memory."""

    async def project_id_for_slug(self, slug: str) -> UUID | None: ...

    async def create_project(self, spec: InitializationProjectSpec) -> UUID: ...

    async def roadmap_ids_by_title(self, project_id: UUID) -> dict[str, UUID]: ...

    async def import_roadmap(
        self,
        project_id: UUID,
        document: RoadmapDocument,
        *,
        submit: bool,
        provenance: WriteProvenance,
    ) -> UUID: ...

    async def task_ids_by_title(self, project_id: UUID) -> dict[str, UUID]: ...

    async def create_task(self, project_id: UUID, task: InitializationTask) -> UUID: ...

    async def link_task_to_step(
        self, project_id: UUID, roadmap_id: UUID, step_key: str, task_id: UUID
    ) -> None: ...

    async def submit_roadmap(self, roadmap_id: UUID, provenance: WriteProvenance) -> None: ...

    async def resolve_resource(
        self, ref: InitializationResourceRef, project_id: UUID | None
    ) -> ResolvedResource | None: ...

    async def attached_resource_id(self, project_id: UUID, resource_id: UUID) -> UUID | None: ...

    async def attach_resource(
        self, project_id: UUID, ref: InitializationResourceRef, resolved: ResolvedResource
    ) -> UUID | None: ...

    async def binding_problem(
        self, binding: InitializationBindingRef, project_id: UUID | None
    ) -> InitializationProblemCode | None: ...

    async def existing_binding_id(
        self, project_id: UUID, binding: InitializationBindingRef
    ) -> UUID | None: ...

    async def apply_binding(
        self, project_id: UUID, binding: InitializationBindingRef
    ) -> UUID | None: ...


def derived_provenance(principal: Principal, write: WriteProvenance) -> Provenance:
    """Server-derived provenance (DEC-0084 §7): the actor is the machine owner
    unless an `agent_id` is declared, in which case the actor is the agent.
    Ownership of that `agent_id` is validated by the write services, never
    here."""
    agent_id = write.agent_id
    return Provenance(
        origin=write.origin,
        actor_type="agent" if agent_id is not None else "user",
        actor_id=agent_id if agent_id is not None else principal.user.id,
        agent_id=agent_id,
        machine_id=principal.machine.id,
        at=datetime.now(UTC),
    )


def _action(
    section: InitializationSection,
    key: str,
    action: InitializationActionKind,
    reason: InitializationReason | None = None,
    resource_id: UUID | None = None,
) -> InitializationAction:
    return InitializationAction(
        section=section, key=key, action=action, reason=reason, resource_id=resource_id
    )


def _problem(
    section: InitializationSection,
    code: InitializationProblemCode,
    *,
    key: str | None = None,
    blocking: bool = True,
    message: str | None = None,
) -> InitializationProblem:
    return InitializationProblem(
        section=section, code=code, key=key, blocking=blocking, message=message
    )


def _roadmap_status(plan: ProjectInitializationPlan) -> Literal["draft", "proposed"] | None:
    if plan.roadmap is None:
        return None
    return "proposed" if plan.mode.value == "proposed" else "draft"


async def reconnoiter(target: InitializationTarget, plan: ProjectInitializationPlan) -> _Recon:
    """Pure planning over the target's read surface. Deterministic: the same
    (plan, state) always yields the same actions/problems, in plan order."""
    recon = _Recon(problems=list(initialization_plan_problems(plan)))

    project_id = await target.project_id_for_slug(plan.project.slug)
    recon.project_id = project_id
    if project_id is None:
        recon.actions.append(
            _action(
                InitializationSection.PROJECT, plan.project.slug, InitializationActionKind.CREATE
            )
        )
    else:
        recon.actions.append(
            _action(
                InitializationSection.PROJECT,
                plan.project.slug,
                InitializationActionKind.REUSE,
                InitializationReason.PROJECT_ALREADY_EXISTS,
            )
        )

    if plan.roadmap is None:
        recon.actions.append(
            _action(
                InitializationSection.ROADMAP,
                plan.project.slug,
                InitializationActionKind.SKIP,
                InitializationReason.NO_ROADMAP,
            )
        )
    else:
        known = await target.roadmap_ids_by_title(project_id) if project_id else {}
        existing_roadmap = known.get(plan.roadmap.title)
        if existing_roadmap is not None:
            recon.roadmap_id = existing_roadmap
            recon.actions.append(
                _action(
                    InitializationSection.ROADMAP,
                    plan.roadmap.title,
                    InitializationActionKind.REUSE,
                    InitializationReason.ROADMAP_ALREADY_EXISTS,
                    resource_id=existing_roadmap,
                )
            )
        else:
            recon.actions.append(
                _action(
                    InitializationSection.ROADMAP,
                    plan.roadmap.title,
                    InitializationActionKind.CREATE,
                )
            )

    if not plan.tasks:
        recon.actions.append(
            _action(
                InitializationSection.TASKS,
                plan.project.slug,
                InitializationActionKind.SKIP,
                InitializationReason.NO_TASKS,
            )
        )
    else:
        existing = await target.task_ids_by_title(project_id) if project_id else {}
        planned_titles: set[str] = set()
        for task in plan.tasks:
            if task.title in existing or task.title in planned_titles:
                recon.actions.append(
                    _action(
                        InitializationSection.TASKS,
                        task.key,
                        InitializationActionKind.REUSE,
                        InitializationReason.TASK_ALREADY_EXISTS,
                    )
                )
                if task.title in existing:
                    recon.reused_task_ids[task.key] = existing[task.title]
            else:
                recon.actions.append(
                    _action(InitializationSection.TASKS, task.key, InitializationActionKind.CREATE)
                )
                recon.create_task_keys.append(task.key)
            planned_titles.add(task.title)

    if not plan.resources:
        recon.actions.append(
            _action(
                InitializationSection.RESOURCES,
                plan.project.slug,
                InitializationActionKind.SKIP,
                InitializationReason.NO_RESOURCES,
            )
        )
    else:
        for ref in plan.resources:
            resolved = await target.resolve_resource(ref, project_id)
            if resolved is None:
                reason = (
                    InitializationReason.RESOURCE_REQUIRED_MISSING
                    if ref.required
                    else InitializationReason.RESOURCE_OPTIONAL_MISSING
                )
                recon.actions.append(
                    _action(
                        InitializationSection.RESOURCES,
                        ref.stable_key,
                        InitializationActionKind.SKIP,
                        reason,
                    )
                )
                recon.problems.append(
                    _problem(
                        InitializationSection.RESOURCES,
                        InitializationProblemCode.RESOURCE_NOT_FOUND,
                        key=ref.stable_key,
                        blocking=ref.required,
                    )
                )
                continue
            recon.resolved_resources[ref.stable_key] = resolved
            attached = (
                await target.attached_resource_id(project_id, resolved.resource_id)
                if project_id is not None
                else None
            )
            if attached is not None:
                recon.actions.append(
                    _action(
                        InitializationSection.RESOURCES,
                        ref.stable_key,
                        InitializationActionKind.REUSE,
                        InitializationReason.RESOURCE_ALREADY_ATTACHED,
                        resource_id=resolved.resource_id,
                    )
                )
            else:
                recon.actions.append(
                    _action(
                        InitializationSection.RESOURCES,
                        ref.stable_key,
                        InitializationActionKind.CREATE,
                        resource_id=resolved.resource_id,
                    )
                )

    if not plan.bindings:
        recon.actions.append(
            _action(
                InitializationSection.BINDINGS,
                plan.project.slug,
                InitializationActionKind.SKIP,
                InitializationReason.NO_BINDINGS,
            )
        )
    else:
        for binding in plan.bindings:
            key = f"{binding.target_kind.value}:{binding.target_stable_key}"
            problem = await target.binding_problem(binding, project_id)
            if problem is not None:
                recon.actions.append(
                    _action(
                        InitializationSection.BINDINGS,
                        key,
                        InitializationActionKind.SKIP,
                        InitializationReason.BINDING_UNAVAILABLE,
                    )
                )
                recon.problems.append(
                    _problem(InitializationSection.BINDINGS, problem, key=key, blocking=True)
                )
                continue
            existing_binding = (
                await target.existing_binding_id(project_id, binding)
                if project_id is not None
                else None
            )
            if existing_binding is not None:
                recon.actions.append(
                    _action(
                        InitializationSection.BINDINGS,
                        key,
                        InitializationActionKind.REUSE,
                        InitializationReason.BINDING_ALREADY_SET,
                        resource_id=existing_binding,
                    )
                )
            else:
                recon.actions.append(
                    _action(InitializationSection.BINDINGS, key, InitializationActionKind.CREATE)
                )

    return recon


def _preview_from(recon: _Recon, plan: ProjectInitializationPlan) -> InitializationPreview:
    blocking = blocking_problems(recon.problems)
    return InitializationPreview(
        valid=not blocking,
        applicable=not blocking,
        roadmap_present=plan.roadmap is not None,
        roadmap_status=_roadmap_status(plan),
        actions=recon.actions,
        summary=count_actions(recon.actions),
        problems=recon.problems,
    )


async def preview_initialization(
    target: InitializationTarget, plan: ProjectInitializationPlan
) -> InitializationPreview:
    """No side effect anywhere on the target's write surface."""
    recon = await reconnoiter(target, plan)
    return _preview_from(recon, plan)


def _invalid_initialization(problems: list[InitializationProblem]) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "error_code": "invalid_initialization",
            "problems": [problem.model_dump(mode="json") for problem in problems],
        },
    )


async def apply_initialization(
    target: InitializationTarget,
    plan: ProjectInitializationPlan,
    principal: Principal,
    provenance: WriteProvenance | None = None,
) -> InitializationResult:
    """Validate, then apply. A blocking problem refuses before any write, so
    the plan is never half-decided; each section then goes through its own
    existing service, and replay reuses whatever already exists (`created=0`)
    rather than duplicating it. Permission matches the existing routes:
    creating a project is provisioning, initializing into an existing one is a
    write."""
    write_provenance = provenance or WriteProvenance()
    recon = await reconnoiter(target, plan)
    blocking = blocking_problems(recon.problems)
    if blocking:
        raise _invalid_initialization(blocking)

    if recon.project_id is None:
        ensure_can_provision(principal, "project")
    ensure_can_write(principal, "initialization")

    project_id = recon.project_id
    if project_id is None:
        project_id = await target.create_project(plan.project)

    roadmap_id = recon.roadmap_id
    if plan.roadmap is not None and roadmap_id is None:
        # A `proposed` roadmap is frozen for review and refuses new Task links, so
        # it is created as a draft, linked, then submitted (DEC-0084 §5/§6).
        roadmap_id = await target.import_roadmap(
            project_id, plan.roadmap, submit=False, provenance=write_provenance
        )
    # `submit_roadmap` is a no-op outside `draft`, so a replay that finds the draft left
    # by an interrupted apply completes the submission instead of leaving it unsubmitted.
    submit_after_links = plan.mode.value == "proposed" and roadmap_id is not None

    task_ids: dict[str, UUID] = dict(recon.reused_task_ids)
    for task in plan.tasks:
        if task.key in recon.create_task_keys:
            task_ids[task.key] = await target.create_task(project_id, task)
    if roadmap_id is not None:
        # Link every planned task that has a step, created or reused: re-linking
        # is a no-op, so a replay repairs a link lost by a partial apply.
        for task in plan.tasks:
            if task.roadmap_step_key is not None and task.key in task_ids:
                await target.link_task_to_step(
                    project_id, roadmap_id, task.roadmap_step_key, task_ids[task.key]
                )
        if submit_after_links:
            await target.submit_roadmap(roadmap_id, write_provenance)

    for ref in plan.resources:
        if not _planned_create(recon, InitializationSection.RESOURCES, ref.stable_key):
            continue
        resolved = recon.resolved_resources.get(ref.stable_key)
        if resolved is not None:
            await target.attach_resource(project_id, ref, resolved)

    for binding in plan.bindings:
        key = f"{binding.target_kind.value}:{binding.target_stable_key}"
        if _planned_create(recon, InitializationSection.BINDINGS, key):
            await target.apply_binding(project_id, binding)

    return InitializationResult(
        applied=True,
        project_id=project_id,
        roadmap_id=roadmap_id,
        roadmap_status=_roadmap_status(plan),
        actions=recon.actions,
        summary=count_actions(recon.actions),
        problems=recon.problems,
        provenance=derived_provenance(principal, write_provenance),
    )


def _planned_create(recon: _Recon, section: InitializationSection, key: str) -> bool:
    return any(
        action.section is section
        and action.key == key
        and action.action is InitializationActionKind.CREATE
        for action in recon.actions
    )


def summarize(result: InitializationPreview | InitializationResult) -> InitializationSummary:
    """Single roll-up accessor shared by preview/apply callers (MCP, HTTP)."""
    return result.summary


class StudioServicesInitializationTarget:
    """Default adapter: reuses existing Studio OS services. `studio_api.services
    .roadmaps` (P3) is imported lazily so this lane builds and tests before P3
    lands; every call site documents the exact interface P3 must provide
    (reconciliation notes in DEC-0087).

    Task creation uses the additive F1 no-commit variant (`add_task`,
    DEC-0084 §1); the remaining section writes still commit through their own
    service. Apply remains replay-safe because every creation is keyed and
    reused; wiring every section into one transaction is a convergence item."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._session = session
        self._principal = principal

    @staticmethod
    def _roadmaps() -> RoadmapServicePort:
        """Lazy so the module imports (and tests run) before P3 lands; the
        typed port is `studio_api.services.roadmap_port`."""
        from importlib import import_module

        return cast(RoadmapServicePort, import_module("studio_api.services.roadmaps"))

    async def project_id_for_slug(self, slug: str) -> UUID | None:
        for project in await projects_service.list_projects(self._session, self._principal):
            if project.slug == slug:
                return project.id
        return None

    async def create_project(self, spec: InitializationProjectSpec) -> UUID:
        project = await projects_service.create_project(
            self._session, spec.slug, spec.name, spec.description, creator=self._principal.user
        )
        self._principal = with_created_project(self._principal, project.id)
        return project.id

    async def roadmap_ids_by_title(self, project_id: UUID) -> dict[str, UUID]:
        result: dict[str, UUID] = {}
        for roadmap in await self._roadmaps().list_roadmaps(
            self._session, self._principal, project_id
        ):
            result[str(roadmap.title)] = roadmap.id
        return result

    async def import_roadmap(
        self,
        project_id: UUID,
        document: RoadmapDocument,
        *,
        submit: bool,
        provenance: WriteProvenance,
    ) -> UUID:
        roadmap = await self._roadmaps().import_roadmap(
            self._session,
            self._principal,
            RoadmapImport(
                project_id=project_id, document=document, submit=submit, provenance=provenance
            ),
        )
        return roadmap.id

    async def task_ids_by_title(self, project_id: UUID) -> dict[str, UUID]:
        tasks = await tasks_service.list_tasks(
            self._session, self._principal, project_id=project_id, limit=1000
        )
        return {task.title: task.id for task in tasks}

    async def create_task(self, project_id: UUID, task: InitializationTask) -> UUID:
        created = await tasks_service.add_task(
            self._session,
            self._principal,
            TaskCreate(project_id=project_id, title=task.title, description=task.description),
        )
        return created.id

    async def link_task_to_step(
        self, project_id: UUID, roadmap_id: UUID, step_key: str, task_id: UUID
    ) -> None:
        # An existing link is a no-op even when the roadmap is frozen for review
        # (`proposed`), so replaying a proposed-mode plan never fails on its own links.
        roadmap = await self._roadmaps().get_roadmap(self._session, self._principal, roadmap_id)
        for phase in roadmap.phases:
            for step in phase.steps:
                if step.key == step_key and any(
                    linked.task_id == task_id for linked in step.linked_tasks
                ):
                    return
        await self._roadmaps().link_task_by_step_key(
            self._session, self._principal, roadmap_id, step_key, task_id
        )

    async def submit_roadmap(self, roadmap_id: UUID, provenance: WriteProvenance) -> None:
        await self._roadmaps().submit_roadmap(
            self._session, self._principal, roadmap_id, provenance
        )

    async def resolve_resource(
        self, ref: InitializationResourceRef, project_id: UUID | None
    ) -> ResolvedResource | None:
        try:
            resolution: LibraryResolution = await library_service.resolve_definition(
                self._session, self._principal, ref.kind, ref.stable_key, project_id=project_id
            )
        except HTTPException:
            return None
        if ref.scope is not None and resolution.scope is not ref.scope:
            return None
        return ResolvedResource(
            resource_id=resolution.resource_id, version=ref.version or resolution.version
        )

    async def attached_resource_id(self, project_id: UUID, resource_id: UUID) -> UUID | None:
        for lock in await library_service.list_locks(self._session, self._principal, project_id):
            if lock.resource_id == resource_id:
                return lock.id
        return None

    async def attach_resource(
        self, project_id: UUID, ref: InitializationResourceRef, resolved: ResolvedResource
    ) -> UUID | None:
        try:
            lock = await library_service.set_lock(
                self._session,
                self._principal,
                LibraryLockCreate(
                    project_id=project_id,
                    resource_id=resolved.resource_id,
                    locked_version=resolved.version,
                ),
            )
        except HTTPException as exc:
            if _error_code(exc) == "already_locked":
                return None
            raise
        return lock.id

    async def binding_problem(
        self, binding: InitializationBindingRef, project_id: UUID | None
    ) -> InitializationProblemCode | None:
        try:
            await library_service.resolve_definition(
                self._session,
                self._principal,
                binding.target_kind,
                binding.target_stable_key,
                project_id=project_id,
            )
        except HTTPException:
            return InitializationProblemCode.BINDING_TARGET_NOT_FOUND
        try:
            verdict = await runtime_bindings_service.resolve_runtime(
                self._session,
                self._principal,
                binding.target_kind,
                binding.target_stable_key,
                project_id=project_id,
                session_overrides={
                    (binding.target_kind, binding.target_stable_key): binding.target
                },
            )
        except HTTPException:
            return InitializationProblemCode.BINDING_TARGET_NOT_FOUND
        if not verdict.compatible:
            return InitializationProblemCode.BINDING_INCOMPATIBLE
        return None

    async def existing_binding_id(
        self, project_id: UUID, binding: InitializationBindingRef
    ) -> UUID | None:
        rows = await runtime_bindings_service.list_bindings(
            self._session,
            self._principal,
            level=binding.level,
            project_id=project_id if binding.level in _PROJECT_LEVELS else None,
            kind=binding.target_kind,
            stable_key=binding.target_stable_key,
        )
        for row in rows:
            if row.level == binding.level.value:
                return row.id
        return None

    async def apply_binding(
        self, project_id: UUID, binding: InitializationBindingRef
    ) -> UUID | None:
        try:
            row = await runtime_bindings_service.create_binding(
                self._session,
                self._principal,
                RuntimeBindingCreate(
                    level=binding.level,
                    project_id=project_id if binding.level in _PROJECT_LEVELS else None,
                    target_kind=binding.target_kind,
                    target_stable_key=binding.target_stable_key,
                    target=binding.target,
                ),
            )
        except HTTPException as exc:
            if _error_code(exc) == "already_bound":
                return None
            raise
        return row.id


def _error_code(exc: HTTPException) -> str | None:
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("error_code")
        return code if isinstance(code, str) else None
    return None
