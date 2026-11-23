"""Plan entitlements and the single limit module (S3-droits-plans).

The limits are data (`plans` / `plan_limits`), the counters are fed by the
phase-M measurements, and every write refusal is the same
`402 plan_limit_reached`. Reads are never blocked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.infra_measurement import InfraMeasurementModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.studio import INTERNAL_STUDIO_ID, StudioMembershipModel, StudioModel
from studio_api.services import provisioning as provisioning_service

GIB = 1024**3
MIB = 1024**2


def _auth(machine: tuple[MachineModel, str]) -> dict[str, str]:
    _, token = machine
    return {"Authorization": f"Bearer {token}"}


async def _measure_storage(
    db_session: AsyncSession, project: ProjectModel, value: int
) -> None:
    db_session.add(
        InfraMeasurementModel(
            metric="storage_bytes",
            project_id=project.id,
            value=value,
            measured_at=datetime.now(UTC),
        )
    )
    await db_session.flush()


async def test_list_studios_returns_only_the_callers_memberships(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    owner = machine[0]
    other_user = await provisioning_service.create_user(
        db_session, "Other", f"{uuid.uuid4()}@example.test", "developer"
    )
    mine = StudioModel(slug=f"mine-{uuid.uuid4().hex[:8]}", name="Mine", plan="pro")
    foreign = StudioModel(slug=f"foreign-{uuid.uuid4().hex[:8]}", name="Foreign")
    db_session.add_all([mine, foreign])
    await db_session.flush()
    db_session.add_all(
        [
            StudioMembershipModel(studio_id=mine.id, user_id=owner.owner_user_id, role="admin"),
            StudioMembershipModel(studio_id=foreign.id, user_id=other_user.id, role="owner"),
        ]
    )
    await db_session.flush()

    response = await client.get("/api/v1/studios", headers=_auth(machine))

    assert response.status_code == 200
    body = response.json()
    ids = {entry["id"] for entry in body}
    assert str(INTERNAL_STUDIO_ID) in ids
    assert str(mine.id) in ids
    assert str(foreign.id) not in ids
    entry = next(item for item in body if item["id"] == str(mine.id))
    assert set(entry) == {"id", "name", "slug", "plan", "status", "role"}
    assert (entry["plan"], entry["role"], entry["status"]) == ("pro", "admin", "active")


async def test_entitlements_expose_plan_declared_limits_and_measured_counters(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    await _measure_storage(db_session, project, 123_456)

    response = await client.get(
        f"/api/v1/studios/{INTERNAL_STUDIO_ID}/entitlements", headers=_auth(machine)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == {"code": "free", "name": "Gratuit", "rank": 0}
    limits = {limit["key"]: limit for limit in body["limits"]}
    assert limits["storage_bytes"]["max_value"] == 2 * GIB
    assert limits["file_size_bytes"]["max_value"] == 100 * MIB
    assert limits["vault_versions_per_note"]["max_value"] == 10
    assert limits["requests_per_minute"]["max_value"] == 60
    counters = {counter["key"]: counter for counter in body["counters"]}
    assert counters["storage_bytes"]["value"] == 123_456
    assert counters["storage_bytes"]["source"] == "measured"
    assert body["upgrade_url"] == "/settings/subscription"


async def test_entitlements_refuse_a_studio_the_caller_does_not_belong_to(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    foreign = StudioModel(slug=f"locked-{uuid.uuid4().hex[:8]}", name="Locked")
    db_session.add(foreign)
    await db_session.flush()

    response = await client.get(
        f"/api/v1/studios/{foreign.id}/entitlements", headers=_auth(machine)
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "forbidden"


async def test_entitlements_unknown_studio_is_404(
    client: AsyncClient, machine: tuple[MachineModel, str]
) -> None:
    response = await client.get(
        f"/api/v1/studios/{uuid.uuid4()}/entitlements", headers=_auth(machine)
    )

    assert response.status_code == 404


async def test_storage_limit_refuses_the_write_and_never_blocks_reads(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    # The measurement alone fills the 2 GiB free plan: the next byte is refused.
    await _measure_storage(db_session, project, 2 * GIB)

    response = await client.post(
        "/api/v1/transfers",
        headers=_auth(machine),
        json={
            "project_id": str(project.id),
            "category": "temporary",
            "filename": "one-byte.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 1,
        },
    )

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["error_code"] == "plan_limit_reached"
    assert detail["limit"] == "storage_bytes"
    assert detail["upgrade_url"] == "/settings/subscription"
    assert detail["max_value"] == 2 * GIB
    assert detail["current"] == 2 * GIB

    listed = await client.get("/api/v1/transfers", headers=_auth(machine))
    assert listed.status_code == 200


async def test_file_size_limit_refuses_the_write(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    await _measure_storage(db_session, project, 0)

    response = await client.post(
        "/api/v1/transfers",
        headers=_auth(machine),
        json={
            "project_id": str(project.id),
            "category": "temporary",
            "filename": "too-big.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 100 * MIB + 1,
        },
    )

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["error_code"] == "plan_limit_reached"
    assert detail["limit"] == "file_size_bytes"
    assert detail["max_value"] == 100 * MIB
