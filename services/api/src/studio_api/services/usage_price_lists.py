"""Central, immutable usage price lists (DEC-0362)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.usage import UsagePriceList, UsagePriceListCreate

from studio_api.db.models.project import ProjectModel
from studio_api.db.models.usage import UsagePriceListModel
from studio_api.services.authz import (
    Principal,
    ensure_project_access,
    ensure_shared_access,
    forbidden,
    get_launch_scope,
    project_in_active_studio,
)

_RESOURCE = "usage_price_list"


def to_price_list(row: UsagePriceListModel) -> UsagePriceList:
    return UsagePriceList.model_validate(row)


def _ensure_reader(principal: Principal, project_id: uuid.UUID | None) -> None:
    if project_id is None:
        ensure_shared_access(principal)
    else:
        ensure_project_access(principal, project_id)


def _ensure_publisher(principal: Principal, project_id: uuid.UUID | None) -> None:
    """Prices are never set by an agent or a launch credential: global lists
    are admin-only, project lists need an admin or a developer with write
    access to the project."""
    if get_launch_scope(principal.machine) is not None:
        raise forbidden(_RESOURCE, "write")
    if project_id is None:
        if principal.role != Role.ADMIN:
            raise forbidden(_RESOURCE, "write")
        return
    if principal.role not in (Role.ADMIN, Role.DEVELOPER):
        raise forbidden(_RESOURCE, "write")
    ensure_project_access(principal, project_id, "write")


def _scope(principal: Principal, project_id: uuid.UUID | None) -> ColumnElement[bool]:
    """Global lists, plus the requested project's own when it belongs to the
    active studio (a foreign project yields the same global-only result as an
    unknown one, DEC-0382)."""
    column = UsagePriceListModel.project_id
    if project_id is None:
        return column.is_(None)
    own_projects = select(ProjectModel.id).where(ProjectModel.studio_id == principal.studio_id)
    return or_(column.is_(None), and_(column == project_id, column.in_(own_projects)))


async def list_price_lists(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID | None
) -> list[UsagePriceListModel]:
    """Global lists, plus the project's own when `project_id` is given,
    newest `effective_from` first."""
    _ensure_reader(principal, project_id)
    stmt = select(UsagePriceListModel).where(_scope(principal, project_id))
    stmt = stmt.order_by(
        UsagePriceListModel.effective_from.desc(), UsagePriceListModel.created_at.desc()
    )
    return list((await session.scalars(stmt)).all())


async def effective_price_list(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID | None, at: datetime
) -> UsagePriceListModel:
    """The list in force at `at`: the project's own when it has one,
    otherwise the global one."""
    _ensure_reader(principal, project_id)
    stmt = (
        select(UsagePriceListModel)
        .where(_scope(principal, project_id), UsagePriceListModel.effective_from <= at)
        .order_by(
            UsagePriceListModel.project_id.is_(None),
            UsagePriceListModel.effective_from.desc(),
            UsagePriceListModel.created_at.desc(),
        )
        .limit(1)
    )
    row = await session.scalar(stmt)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail={"error_code": "price_list_not_found"}
        )
    return row


def _conflict() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"error_code": "price_list_conflict"})


async def create_price_list(
    session: AsyncSession,
    principal: Principal,
    payload: UsagePriceListCreate,
    *,
    commit: bool = True,
) -> UsagePriceListModel:
    _ensure_publisher(principal, payload.project_id)
    if payload.project_id is not None and not await project_in_active_studio(
        session, principal, payload.project_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    existing = await session.scalar(
        select(UsagePriceListModel.id).where(
            UsagePriceListModel.price_list_id == payload.price_list_id
        )
    )
    if existing is not None:
        raise _conflict()
    document = payload.model_dump(mode="json")
    row = UsagePriceListModel(
        price_list_id=payload.price_list_id,
        project_id=payload.project_id,
        currency=payload.currency,
        effective_from=payload.effective_from,
        models=document["models"],
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise _conflict() from exc
    await session.refresh(row)
    if commit:
        await session.commit()
    return row
