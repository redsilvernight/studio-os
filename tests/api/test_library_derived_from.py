from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.services import library as library_service
from studio_contracts.library import (
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersionCreate,
    LibraryVersionRef,
)

from tests.api.test_library_resolution import _create, _principal


async def test_user_version_carries_derived_from(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    principal = await _principal(db_session, machine)
    common = await _create(db_session, principal, "derives")
    override, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=LibraryKind.RULE,
            stable_key="derives",
            scope=LibraryScope.USER,
            title="mine",
            content={"content_schema": "studio.library.rule/v1", "text": "mine"},
            derived_from=LibraryVersionRef(resource_id=common.id, version=1),
        ),
    )
    detail = await library_service.version_detail(
        db_session, (await library_service.list_versions(db_session, override.id))[0]
    )
    assert detail.derived_from == LibraryVersionRef(resource_id=common.id, version=1)

    plain = await library_service.create_resource_version(
        db_session,
        principal,
        override,
        LibraryVersionCreate(
            title="v2", content={"content_schema": "studio.library.rule/v1", "text": "v2"}
        ),
    )
    assert (await library_service.version_detail(db_session, plain)).derived_from is None


@pytest.mark.parametrize(("case", "expected"), [("key_mismatch", 422), ("absent_version", 404)])
async def test_derived_from_rejects_invalid_source(
    db_session: AsyncSession, machine: tuple[MachineModel, str], case: str, expected: int
) -> None:
    principal = await _principal(db_session, machine)
    common = await _create(db_session, principal, "src")
    other = await _create(db_session, principal, "other")
    ref = (
        LibraryVersionRef(resource_id=common.id, version=1)
        if case == "key_mismatch"
        else LibraryVersionRef(resource_id=other.id, version=9)
    )
    key = "fresh" if case == "key_mismatch" else "other"
    with pytest.raises(HTTPException) as exc_info:
        await library_service.create_resource(
            db_session,
            principal,
            LibraryResourceCreate(
                kind=LibraryKind.RULE,
                stable_key=key,
                scope=LibraryScope.USER,
                title="t",
                content={"content_schema": "studio.library.rule/v1", "text": "x"},
                derived_from=ref,
            ),
        )
    assert exc_info.value.status_code == expected
