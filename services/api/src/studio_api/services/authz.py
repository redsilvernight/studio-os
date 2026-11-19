from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Literal, TypeGuard

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.studio import (
    INTERNAL_STUDIO_ID,
    StudioMembershipModel,
    StudioRole,
)
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.user import UserModel

LAUNCH_SCOPE_ATTR = "launch_scope"

STUDIO_MANAGER_ROLES = frozenset({StudioRole.OWNER, StudioRole.ADMIN})
"""Studio roles that can manage the studio and reach every project it owns."""

_STUDIO_ROLE_RANK = {
    StudioRole.VIEWER: 0,
    StudioRole.MEMBER: 1,
    StudioRole.ADMIN: 2,
    StudioRole.OWNER: 3,
}


def is_studio_manager(principal: Principal) -> bool:
    """`owner`/`admin` of the active studio. Replaces every former check on the
    global `Role.ADMIN`, which no longer grants implicit reach."""
    return principal.studio_role in STUDIO_MANAGER_ROLES


def owns_agent(agent: AgentModel | None, machine: MachineModel) -> TypeGuard[AgentModel]:
    if agent is None:
        return False
    if agent.owner_user_id is not None:
        return agent.owner_user_id == machine.owner_user_id
    return agent.machine_id == machine.id


@dataclass(frozen=True)
class LaunchScope:
    """What an ephemeral launch credential is bound to. Carried on the
    resolved machine for the duration of one request or tool call."""

    launch_id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID


def get_launch_scope(machine: MachineModel) -> LaunchScope | None:
    scope = getattr(machine, LAUNCH_SCOPE_ATTR, None)
    return scope if isinstance(scope, LaunchScope) else None


@dataclass(frozen=True)
class StudioWide:
    """Scope of an `owner`/`admin`: every project of ONE studio, including
    projects created later and ids that do not exist (those answer 404 from the
    lookup, as for the former global admin). Never reaches another studio: a
    guard given the project's studio refuses a mismatch, and a listing is
    restricted to `projects.studio_id`."""

    studio_id: uuid.UUID


ProjectScope = StudioWide | frozenset[uuid.UUID]
"""`StudioWide` for `owner`/`admin`; for `member`/`viewer` their project
memberships intersected with the active studio's projects."""

ProjectAction = Literal["read", "write"]


@dataclass(frozen=True)
class ActiveStudio:
    """The studio one request acts in, and the User's role there."""

    studio_id: uuid.UUID
    role: StudioRole


async def resolve_active_studio(
    session: AsyncSession,
    user: UserModel,
    requested: uuid.UUID | None = None,
    preferred: uuid.UUID | None = None,
) -> ActiveStudio:
    """Single source of the active studio, by priority: the request's
    `requested` studio (JWT claim, then `X-Studio-Id`, then `machines.studio_id`)
    must match one of the user's memberships — a mismatching or unknown value
    answers the same 403, never an existence oracle.

    Without a request: exactly one membership wins as-is; otherwise the
    internal studio when the user is one of its members (it owns pre-0046
    data); otherwise the oldest membership. No membership at all is
    fail-closed."""
    result = await session.execute(
        select(StudioMembershipModel)
        .where(StudioMembershipModel.user_id == user.id)
        .order_by(StudioMembershipModel.created_at, StudioMembershipModel.studio_id)
    )
    memberships = list(result.scalars().all())
    if requested is not None:
        for membership in memberships:
            if membership.studio_id == requested:
                return ActiveStudio(membership.studio_id, StudioRole(membership.role))
        raise forbidden("studio", "read")
    if preferred is not None:
        # The machine's stored choice is a preference, not a request: once the
        # user is no longer a member of it, the default applies instead of a
        # permanent 403.
        for membership in memberships:
            if membership.studio_id == preferred:
                return ActiveStudio(membership.studio_id, StudioRole(membership.role))
    if len(memberships) == 1:
        membership = memberships[0]
        return ActiveStudio(membership.studio_id, StudioRole(membership.role))
    internal = next((m for m in memberships if m.studio_id == INTERNAL_STUDIO_ID), None)
    if internal is not None:
        return ActiveStudio(internal.studio_id, StudioRole(internal.role))
    if not memberships:
        raise forbidden("studio", "read")
    oldest = memberships[0]
    return ActiveStudio(oldest.studio_id, StudioRole(oldest.role))


async def studio_role_for_user(
    session: AsyncSession, user_id: uuid.UUID, studio_id: uuid.UUID
) -> StudioRole | None:
    """The user's role in that studio, or `None` when it is not a member."""
    role = await session.scalar(
        select(StudioMembershipModel.role).where(
            StudioMembershipModel.user_id == user_id,
            StudioMembershipModel.studio_id == studio_id,
        )
    )
    return None if role is None else StudioRole(role)


@dataclass(frozen=True)
class Principal:
    """The levels authorization is checked against, composed with AND
    (TECH/04, DEC-0036, DEC-0103, DEC-0382): the active studio and the User's
    role there (`studio_role`), the transverse account `role` (machine/agent
    capabilities only), project access (`project_scope`, always bounded by the
    active studio) and, per resource, ownership derived from the resource's own
    existing link to a machine/user. `is_operator` unlocks instance operations
    only — it is never consulted by a content visibility clause.

    `project_scope` defaults to no project at all: a Principal built anywhere
    but `load_principal` is fail-closed."""

    machine: MachineModel
    user: UserModel
    role: Role
    studio_id: uuid.UUID
    studio_role: StudioRole
    is_operator: bool = False
    project_scope: ProjectScope = field(default_factory=frozenset)
    human_authenticated: bool = False


async def load_principal(
    session: AsyncSession,
    machine: MachineModel,
    requested_studio_id: uuid.UUID | None = None,
) -> Principal:
    """Loaded once per request/tool call (DEC-0103 §12, DEC-0382 §3). A Machine
    inherits its owner's memberships; an Agent never has any of its own.

    A launch credential stays bound to its project's studio: `requested_studio_id`
    is ignored for it, so a header can never redirect an ephemeral credential to
    another studio."""
    user = await session.get(UserModel, machine.owner_user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "machine owner not found")
    role = Role(user.role)
    launch_scope = get_launch_scope(machine)
    if launch_scope is not None:
        studio_id, studio_role = await _launch_studio(session, user, launch_scope)
        project_scope = await load_project_scope(session, user.id, studio_id, studio_role)
        allowed = scope_contains(project_scope, launch_scope.project_id)
        project_scope = frozenset({launch_scope.project_id}) if allowed else frozenset()
    else:
        active = await resolve_active_studio(
            session, user, requested_studio_id, preferred=machine.studio_id
        )
        studio_id, studio_role = active.studio_id, active.role
        project_scope = await load_project_scope(session, user.id, studio_id, studio_role)
    return Principal(
        machine=machine,
        user=user,
        role=role,
        studio_id=studio_id,
        studio_role=studio_role,
        is_operator=user.is_operator,
        project_scope=project_scope,
    )


async def _launch_studio(
    session: AsyncSession, user: UserModel, launch_scope: LaunchScope
) -> tuple[uuid.UUID, StudioRole]:
    """The studio owning the launch's project, and the launcher's role there.
    A missing project or membership is fail-closed (`viewer`, empty scope)."""
    studio_id = await session.scalar(
        select(ProjectModel.studio_id).where(ProjectModel.id == launch_scope.project_id)
    )
    if studio_id is None:
        return INTERNAL_STUDIO_ID, StudioRole.VIEWER
    studio_role = await studio_role_for_user(session, user.id, studio_id)
    return studio_id, StudioRole.VIEWER if studio_role is None else studio_role


async def load_project_scope(
    session: AsyncSession,
    user_id: uuid.UUID,
    studio_id: uuid.UUID,
    studio_role: StudioRole,
) -> ProjectScope:
    """Concrete project ids the user may reach inside that studio: every
    project of the studio for `owner`/`admin`, their own memberships
    intersected with the studio's projects for `member`/`viewer`. Joining on
    `projects.studio_id` is what keeps another studio's projects out of reach."""
    if studio_role in STUDIO_MANAGER_ROLES:
        return StudioWide(studio_id)
    rows = await session.execute(
        select(ProjectMembershipModel.project_id)
        .join(ProjectModel, ProjectModel.id == ProjectMembershipModel.project_id)
        .where(
            ProjectMembershipModel.user_id == user_id,
            ProjectModel.studio_id == studio_id,
        )
    )
    return frozenset(rows.scalars().all())


async def project_access_for_user(
    session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID
) -> bool:
    """Project access for a user without a loaded Principal (stream
    revalidation, eligibility of another user's machines): resolved in the
    studio that owns the project, never in a default one."""
    studio_id = await session.scalar(
        select(ProjectModel.studio_id).where(ProjectModel.id == project_id)
    )
    if studio_id is None:
        return False
    studio_role = await studio_role_for_user(session, user_id, studio_id)
    if studio_role is None:
        return False
    scope = await load_project_scope(session, user_id, studio_id, studio_role)
    return scope_contains(scope, project_id)


def with_created_project(principal: Principal, project_id: uuid.UUID) -> Principal:
    """The Principal is loaded once per request (DEC-0103 §12), before a
    project the request itself creates. Its creator is granted in the same
    commit (§5), so the rest of the request sees that project too."""
    scope = principal.project_scope
    if isinstance(scope, StudioWide):
        return principal
    return replace(principal, project_scope=scope | {project_id})


def has_project_access(
    principal: Principal, project_id: uuid.UUID, project_studio_id: uuid.UUID | None = None
) -> bool:
    """`project_studio_id`, when the caller already loaded the project, must be
    the active studio: the same id can exist in another tenant, and a scope is
    only ever meaningful inside the studio it was loaded for."""
    if project_studio_id is not None and project_studio_id != principal.studio_id:
        return False
    return scope_contains(principal.project_scope, project_id)


def scope_contains(scope: ProjectScope, project_id: uuid.UUID) -> bool:
    """Membership test of a scope; `StudioWide` holds any id of its studio (the
    caller's lookup then answers 404 for an unknown one)."""
    return isinstance(scope, StudioWide) or project_id in scope


def has_any_project(principal: Principal) -> bool:
    """Shared data without a project (global decisions, Studio Library and
    bindings, project-less transfers) is readable only by a studio manager or a
    User with at least one project membership in the active studio
    (DEC-0103 §4)."""
    scope = principal.project_scope
    return isinstance(scope, StudioWide) or bool(scope)


def ensure_project_access(
    principal: Principal,
    project_id: uuid.UUID,
    action: ProjectAction = "read",
    project_studio_id: uuid.UUID | None = None,
) -> None:
    """The canonical project check (DEC-0103 §8/§12). Inaccessible and
    nonexistent projects answer the same 403 — no existence oracle — so this
    runs before any lookup, idempotency short-circuit or `event_id` dedup."""
    if not has_project_access(principal, project_id, project_studio_id):
        raise forbidden("project", action)


def ensure_shared_access(principal: Principal, action: ProjectAction = "read") -> None:
    """Guard for project-less shared data (see `has_any_project`)."""
    if not has_any_project(principal):
        raise forbidden("project", action)


def studio_clause(
    principal: Principal,
    column: Any,
    project_column: Any | None = None,
) -> ColumnElement[bool]:
    """Filter for a studio-scoped collection: `column` (the resource's
    `studio_id`) must be the active studio and, when the resource also carries a
    `project_column`, its project must be visible to the principal. `owner`/
    `admin` still see every project of their studio, never another studio's."""
    clause: ColumnElement[bool] = column == principal.studio_id
    if project_column is not None:
        clause = and_(clause, project_visibility_clause(principal, project_column))
    return clause


def project_visibility_clause(principal: Principal, column: Any) -> ColumnElement[bool]:
    """Filter for listing a project-scoped collection: silently restricted to
    accessible projects, never counting invisible rows (DEC-0103 §7). A
    nullable `project_id` column keeps its project-less rows only for a
    Principal that `has_any_project`."""
    scope = principal.project_scope
    if isinstance(scope, StudioWide):
        clause: ColumnElement[bool] = column.in_(
            select(ProjectModel.id).where(ProjectModel.studio_id == scope.studio_id)
        )
    elif not scope:
        clause = false()
    else:
        clause = column.in_(scope)
    if column.nullable:
        return or_(clause, column.is_(None))
    return clause


def forbidden(resource: str, action: str) -> HTTPException:
    """No confidentiality 404 (TECH/04 Autorisation) — a caller with no
    access to an existing resource gets 403 with this machine-readable
    envelope, never a generic-looking 404 that would let it distinguish
    "forbidden" from "doesn't exist". Documented exceptions (User-owned resources: Library
    User scope, runtime bindings, runtimes, machine revoke) answer 404 on
    purpose, matching their owner-filtered lists. Exported (not `_`-private) so a
    resource-specific ownership check that needs its own DB lookup (e.g.
    ai-work's agent-derived ownership) can raise the same shape without
    duplicating it."""
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail={"error_code": "forbidden", "resource": resource, "action": action},
    )


def ensure_studio_role(principal: Principal, min_role: StudioRole) -> None:
    """Studio management gate: `owner` and `admin` manage, `member` writes and
    `viewer` reads. The account `role` is never consulted here."""
    if _STUDIO_ROLE_RANK[principal.studio_role] < _STUDIO_ROLE_RANK[min_role]:
        raise forbidden("studio", min_role.value)


def ensure_operator(principal: Principal) -> None:
    """Instance-level operations only (`is_operator`). Deliberately absent from
    every visibility clause: an operator without a studio membership reads no
    content."""
    if not principal.is_operator:
        raise forbidden("instance", "operate")


def ensure_can_write(principal: Principal, resource: str) -> None:
    """A studio `viewer` and the account `readonly` never write shared state
    anywhere. Heartbeat is the one explicit exception (TECH/04) and
    deliberately never calls this."""
    if principal.role == Role.READONLY or principal.studio_role == StudioRole.VIEWER:
        raise forbidden(resource, "write")


def ensure_can_provision(principal: Principal, resource: str) -> None:
    """`agent` gets every `developer` write except provisioning (new projects,
    machines, users). A studio `owner`/`admin` may provision; `member` and
    `viewer` may not."""
    if is_studio_manager(principal) or principal.role == Role.DEVELOPER:
        return
    raise forbidden(resource, "provision")


def ensure_machine_owned(
    principal: Principal,
    owner_machine_id: uuid.UUID | None,
    resource: str,
    action: str = "write",
) -> None:
    """Ownership for a resource whose owning machine is one of its own
    columns (task claim/release, claim renew/release, session end, ai-work
    PATCH): only the owning machine or a studio owner/admin may mutate it. A
    resource with no owning machine yet (`owner_machine_id is None`) is unowned
    and open to any writer past `ensure_can_write`."""
    ensure_can_write(principal, resource)
    if is_studio_manager(principal):
        return
    if owner_machine_id is not None and owner_machine_id != principal.machine.id:
        raise forbidden(resource, action)


def ensure_transfer_access(principal: Principal, transfer: TransferModel, action: str) -> None:
    """The one concretely exploitable gap the audit found: `sender_user_id`
    / `recipient_user_id` (`None` recipient = broadcast, e.g. a project
    build/asset) drive access, not just "any authenticated machine".
    `action="read"` (metadata, download-url) is open to sender, recipient,
    broadcast and a studio owner/admin — `readonly` included, since it's a
    read. Any other action (upload/initiate, upload/complete, delete) is sender
    or studio owner/admin only — never the recipient, never a broadcast reader,
    never `readonly`. A transfer of another studio is invisible to all."""
    if transfer.studio_id != principal.studio_id:
        raise forbidden("transfer", action)
    is_sender = transfer.sender_user_id == principal.user.id
    is_recipient = transfer.recipient_user_id == principal.user.id
    is_broadcast = transfer.recipient_user_id is None
    is_manager = is_studio_manager(principal)
    if action == "read":
        if is_sender or is_recipient or is_broadcast or is_manager:
            return
        raise forbidden("transfer", action)
    if is_manager or is_sender:
        ensure_can_write(principal, "transfer")
        return
    raise forbidden("transfer", action)


def transfer_visibility_clause(principal: Principal) -> ColumnElement[bool]:
    """Filter for listing transfers: always restricted to the active studio,
    then to the same conditions as `ensure_transfer_access(..., "read")`,
    applied as a query filter instead of a 403 so a list never reveals a
    forbidden transfer's existence. `owner`/`admin` see every transfer of their
    studio; `is_operator` adds nothing."""
    studio = TransferModel.studio_id == principal.studio_id
    if is_studio_manager(principal):
        return studio
    return and_(
        studio,
        or_(
            TransferModel.sender_user_id == principal.user.id,
            TransferModel.recipient_user_id == principal.user.id,
            TransferModel.recipient_user_id.is_(None),
        ),
    )
