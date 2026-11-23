"""Plan entitlements and the single limit module (S3-droits-plans).

The limits are data (`plans` / `plan_limits`), the counters are fed by the
phase-M measurements, and every write refusal is the same
`402 plan_limit_reached`. Reads are never blocked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.infra_measurement import InfraMeasurementModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.plan import PlanLimitModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.studio import INTERNAL_STUDIO_ID, StudioMembershipModel, StudioModel
from studio_api.services import entitlements as entitlements_service
from studio_api.services import event_stream
from studio_api.services import provisioning as provisioning_service

GIB = 1024**3
MIB = 1024**2


def _auth(machine: tuple[MachineModel, str]) -> dict[str, str]:
    _, token = machine
    return {"Authorization": f"Bearer {token}"}


async def _measure_storage(db_session: AsyncSession, project: ProjectModel, value: int) -> None:
    db_session.add(
        InfraMeasurementModel(
            metric="storage_bytes",
            project_id=project.id,
            value=value,
            measured_at=datetime.now(UTC),
        )
    )
    await db_session.flush()


async def _set_free_limit(db_session: AsyncSession, key: str, value: int) -> None:
    await db_session.execute(
        update(PlanLimitModel)
        .where(PlanLimitModel.plan_code == "free", PlanLimitModel.limit_key == key)
        .values(max_value=value)
    )
    await db_session.flush()


def _assert_plan_limit(response: Response, limit: str, max_value: int, current: int) -> None:
    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["error_code"] == "plan_limit_reached"
    assert detail["limit"] == limit
    assert detail["max_value"] == max_value
    assert detail["current"] == current
    assert detail["upgrade_url"] == "/settings/subscription"


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


async def test_members_limit_refuses_a_new_member_but_not_the_directory(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_machine: tuple[MachineModel, str],
) -> None:
    # The operator's own membership already fills the lowered ceiling. The
    # test harness backfills a membership for every new User on flush, so the
    # rejected account is already counted when the guard runs (current=2).
    await _set_free_limit(db_session, entitlements_service.MEMBERS, 1)

    response = await client.post(
        "/api/v1/users",
        headers=_auth(admin_machine),
        json={"display_name": "Another", "email": f"{uuid.uuid4()}@example.test"},
    )

    _assert_plan_limit(response, "members", 1, 2)
    listed = await client.get("/api/v1/users", headers=_auth(admin_machine))
    assert listed.status_code == 200


async def test_machines_limit_refuses_registration_but_not_listing(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_machine: tuple[MachineModel, str],
) -> None:
    await _set_free_limit(db_session, entitlements_service.MACHINES, 1)

    response = await client.post(
        "/api/v1/machines",
        headers=_auth(admin_machine),
        json={"display_name": "second-machine"},
    )

    _assert_plan_limit(response, "machines", 1, 1)
    listed = await client.get("/api/v1/machines", headers=_auth(admin_machine))
    assert listed.status_code == 200


async def test_vault_versions_limit_refuses_a_write_but_not_the_history(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    await _set_free_limit(db_session, entitlements_service.VAULT_VERSIONS_PER_NOTE, 1)
    created = await client.post(
        "/api/v1/vault/notes",
        headers=_auth(machine),
        json={
            "scope": "studio",
            "slug": f"limit-{uuid.uuid4().hex[:8]}",
            "title": "One version",
            "body": "body",
        },
    )
    assert created.status_code == 201
    note_id = created.json()["id"]

    response = await client.patch(
        f"/api/v1/vault/notes/{note_id}",
        headers=_auth(machine),
        json={"expected_version": 1, "title": "Second version"},
    )

    # Per-item ceilings report `current=0`: the ceiling is on the requested
    # value itself (version 2), not on a cumulative counter.
    _assert_plan_limit(response, "vault_versions_per_note", 1, 0)
    history = await client.get(f"/api/v1/vault/notes/{note_id}/versions", headers=_auth(machine))
    assert history.status_code == 200
    assert [v["version"] for v in history.json()["items"]] == [1]


async def test_sse_connections_limit_refuses_opening_without_closing_existing_clients(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    # No collector run in this test: the measurement gives a deterministic
    # counter at the free plan's ceiling (5).
    db_session.add(
        InfraMeasurementModel(metric="sse_connections", value=5, measured_at=datetime.now(UTC))
    )
    await db_session.flush()
    before = event_stream.subscriber_count()

    response = await client.get("/api/v1/events/stream", headers=_auth(machine))

    _assert_plan_limit(response, "sse_connections", 5, 5)
    assert event_stream.subscriber_count() == before
    listed = await client.get("/api/v1/events", headers=_auth(machine))
    assert listed.status_code == 200


async def test_requests_per_minute_refuses_a_write_but_not_reads(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    entitlements_service.reset_request_windows()
    await _set_free_limit(db_session, entitlements_service.REQUESTS_PER_MINUTE, 2)
    try:
        for index in range(2):
            created = await client.post(
                "/api/v1/vault/notes",
                headers=_auth(machine),
                json={
                    "scope": "studio",
                    "slug": f"rpm-{uuid.uuid4().hex[:8]}",
                    "title": f"Write {index}",
                    "body": "body",
                },
            )
            assert created.status_code == 201

        response = await client.post(
            "/api/v1/vault/notes",
            headers=_auth(machine),
            json={
                "scope": "studio",
                "slug": f"rpm-{uuid.uuid4().hex[:8]}",
                "title": "Too many",
                "body": "body",
            },
        )

        _assert_plan_limit(response, "requests_per_minute", 2, 2)
        listed = await client.get("/api/v1/vault/tree", headers=_auth(machine))
        assert listed.status_code == 200
    finally:
        entitlements_service.reset_request_windows()


async def test_studios_per_account_limit_refuses_creation_but_not_listing(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_machine: tuple[MachineModel, str],
) -> None:
    await _set_free_limit(db_session, entitlements_service.STUDIOS_PER_ACCOUNT, 1)

    first = await client.post(
        "/api/v1/studios", headers=_auth(admin_machine), json={"name": "Atelier"}
    )
    assert first.status_code == 201
    assert first.json()["role"] == "owner"

    second = await client.post(
        "/api/v1/studios", headers=_auth(admin_machine), json={"name": "Autre"}
    )
    _assert_plan_limit(second, "studios_per_account", 1, 1)
    listed = await client.get("/api/v1/studios", headers=_auth(admin_machine))
    assert listed.status_code == 200
