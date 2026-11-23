"""Studio-scope Library writes are admin-only (P70a): tests seed the shared
Studio layer through this admin principal, then exercise the behaviour under
test with their own (developer) principal."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import Principal, load_principal


async def studio_admin(db_session: AsyncSession) -> Principal:
    # One seeder per test session: each account is a studio member, so a
    # fresh one per call would hit the plan's member ceiling in seed loops.
    cached = db_session.info.get("studio_admin_machine")
    if cached is not None:
        return await load_principal(db_session, cached)
    user = await provisioning_service.create_user(
        db_session, "Studio Seeder", f"{uuid.uuid4()}@example.test", "admin"
    )
    machine, _ = await provisioning_service.create_machine(db_session, user.id, "seed-machine")
    db_session.info["studio_admin_machine"] = machine
    return await load_principal(db_session, machine)
