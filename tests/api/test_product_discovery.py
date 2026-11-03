from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.build import GitHubIntegrationModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.main import app
from studio_api.services.discovery import CATALOGUE

PATH = "/api/v1/capabilities"


def test_catalogue_only_advertises_existing_product_endpoints() -> None:
    paths = app.openapi()["paths"]
    assert all(spec.endpoint in paths for spec in CATALOGUE), [
        spec.endpoint for spec in CATALOGUE if spec.endpoint not in paths
    ]
    assert len({spec.key for spec in CATALOGUE}) == len(CATALOGUE)


async def test_compact_summary_then_detail_with_example_and_prerequisites(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    summary = await client.get(PATH, headers=auth_headers)
    assert summary.status_code == 200, summary.text
    assert len(summary.json()["capabilities"]) == 6
    assert summary.json()["additional_available"] == len(CATALOGUE) - 6
    assert all(item["example"] is None for item in summary.json()["capabilities"])
    detail = await client.get(PATH, headers=auth_headers, params={"key": "vault"})
    assert detail.status_code == 200, detail.text
    capability = detail.json()["capabilities"][0]
    assert capability["example"]
    assert capability["prerequisites"]


async def test_readonly_sees_available_reads_but_cannot_write_or_launch(
    client: AsyncClient,
    readonly_auth_headers: dict[str, str],
) -> None:
    decisions = await client.get(PATH, headers=readonly_auth_headers, params={"key": "decisions"})
    assert decisions.status_code == 200, decisions.text
    item = decisions.json()["capabilities"][0]
    assert item["state"] == "available"
    assert item["write_allowed"] is False
    assert any("admin" in restriction for restriction in item["restrictions"])
    launches = await client.get(PATH, headers=readonly_auth_headers, params={"key": "launches"})
    assert launches.json()["capabilities"][0]["state"] == "not_authorized"


async def test_machine_configuration_and_unsupported_installation_are_distinct(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
    project: ProjectModel,
) -> None:
    missing = await client.get(PATH, headers=auth_headers, params={"key": "launches"})
    assert missing.json()["capabilities"][0]["state"] == "needs_configuration"
    machine[0].capabilities = {
        "harnesses": [{"harness_id": "codex", "detected": True, "configured": True}],
        "project_ids": [str(project.id)],
        "accepts_launches": True,
        "max_launches": 1,
        "launch_safety": False,
    }
    machine[0].capabilities_reported_at = datetime.now(UTC)
    await db_session.commit()
    unsupported = await client.get(PATH, headers=auth_headers, params={"key": "launches"})
    assert unsupported.json()["capabilities"][0]["state"] == "unsupported"
    machine[0].capabilities = {**machine[0].capabilities, "launch_safety": True}
    await db_session.commit()
    ready = await client.get(PATH, headers=auth_headers, params={"key": "launches"})
    assert ready.json()["capabilities"][0]["state"] == "available"


@pytest.mark.isolation
async def test_private_projects_and_ci_configuration_are_not_exposed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    other_machine: tuple[MachineModel, str],
) -> None:
    db_session.add(
        GitHubIntegrationModel(
            project_id=project.id,
            repo_full_name="private-org/private-repo",
            enabled=True,
            created_by_user_id=other_machine[0].owner_user_id,
        )
    )
    await db_session.commit()
    response = await client.get(PATH, headers=auth_headers, params={"key": "builds"})
    assert response.status_code == 200, response.text
    assert response.json()["capabilities"][0]["state"] == "needs_configuration"
    assert "private-org" not in response.text
    assert str(project.id) not in response.text


async def test_start_project_and_bounds(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    start = await client.get(PATH, headers=auth_headers, params={"intent": "start_project"})
    assert start.status_code == 200, start.text
    assert start.json()["next_steps"]
    assert len(start.json()["capabilities"]) <= 6
    invalid = await client.get(PATH, headers=auth_headers, params={"limit": 999})
    assert invalid.status_code == 422
    unknown = await client.get(PATH, headers=auth_headers, params={"key": "not-real"})
    assert unknown.status_code == 404
