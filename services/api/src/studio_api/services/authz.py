from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, or_
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.user import UserModel


@dataclass(frozen=True)
class Principal:
    """The two levels authorization is checked against (TECH/04, DEC-0036):
    a transverse role (`role`, the owner of the authenticated machine) and,
    per resource, ownership derived from the resource's own existing link to
    a machine/user — never a separate ACL table."""

    machine: MachineModel
    user: UserModel
    role: Role


async def load_principal(session: AsyncSession, machine: MachineModel) -> Principal:
    user = await session.get(UserModel, machine.owner_user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "machine owner not found")
    return Principal(machine=machine, user=user, role=Role(user.role))


def forbidden(resource: str, action: str) -> HTTPException:
    """No confidentiality 404 (TECH/04 Autorisation) — a caller with no
    access to an existing resource gets 403 with this machine-readable
    envelope, never a generic-looking 404 that would let it distinguish
    "forbidden" from "doesn't exist". Exported (not `_`-private) so a
    resource-specific ownership check that needs its own DB lookup (e.g.
    ai-work's agent-derived ownership) can raise the same shape without
    duplicating it."""
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail={"error_code": "forbidden", "resource": resource, "action": action},
    )


def ensure_can_write(principal: Principal, resource: str) -> None:
    """`readonly` never writes shared state anywhere. Heartbeat is the one
    explicit exception (TECH/04) and deliberately never calls this."""
    if principal.role == Role.READONLY:
        raise forbidden(resource, "write")


def ensure_can_provision(principal: Principal, resource: str) -> None:
    """`agent` gets every `developer` write except provisioning (new
    projects, machines, users) — the role check `require_roles` already
    applies to those endpoints; this is the equivalent for a service-layer
    caller that isn't behind that dependency."""
    if principal.role not in (Role.ADMIN, Role.DEVELOPER):
        raise forbidden(resource, "provision")


def ensure_machine_owned(
    principal: Principal,
    owner_machine_id: uuid.UUID | None,
    resource: str,
    action: str = "write",
) -> None:
    """Ownership for a resource whose owning machine is one of its own
    columns (task claim/release, claim renew/release, session end, ai-work
    PATCH): only the owning machine or an admin may mutate it. A resource
    with no owning machine yet (`owner_machine_id is None`) is unowned and
    open to any writer past `ensure_can_write`."""
    ensure_can_write(principal, resource)
    if principal.role == Role.ADMIN:
        return
    if owner_machine_id is not None and owner_machine_id != principal.machine.id:
        raise forbidden(resource, action)


def ensure_transfer_access(principal: Principal, transfer: TransferModel, action: str) -> None:
    """The one concretely exploitable gap the audit found: `sender_user_id`
    / `recipient_user_id` (`None` recipient = broadcast, e.g. a project
    build/asset) drive access, not just "any authenticated machine".
    `action="read"` (metadata, download-url) is open to sender, recipient,
    broadcast and admin — `readonly` included, since it's a read. Any other
    action (upload/initiate, upload/complete, delete) is sender or admin
    only — never the recipient, never a broadcast reader, never `readonly`."""
    is_sender = transfer.sender_user_id == principal.user.id
    is_recipient = transfer.recipient_user_id == principal.user.id
    is_broadcast = transfer.recipient_user_id is None
    is_admin = principal.role == Role.ADMIN
    if action == "read":
        if is_sender or is_recipient or is_broadcast or is_admin:
            return
        raise forbidden("transfer", action)
    if is_admin or is_sender:
        ensure_can_write(principal, "transfer")
        return
    raise forbidden("transfer", action)


def transfer_visibility_clause(principal: Principal) -> ColumnElement[bool] | None:
    """Filter for listing transfers: the same four conditions as
    `ensure_transfer_access(..., "read")`, applied as a query filter instead
    of a 403 so a list never reveals a forbidden transfer's existence.
    `None` means "no filter" (admin sees everything)."""
    if principal.role == Role.ADMIN:
        return None
    return or_(
        TransferModel.sender_user_id == principal.user.id,
        TransferModel.recipient_user_id == principal.user.id,
        TransferModel.recipient_user_id.is_(None),
    )
