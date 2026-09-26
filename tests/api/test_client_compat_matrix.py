from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.session import get_session
from studio_api.main import create_app
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import Settings

from tests.api.conftest import TEST_DATABASE_URL

# C1 contract matrix: an N-1 client still inside the supported window keeps
# working end-to-end (auth included), the current build is never flagged, and a
# build below the minimum is refused on every surface — deterministically, so a
# client cannot be tempted into an infinite retry. Exercised against a real app
# built with an explicit window (0.1.0 supported, 0.2.0 latest), same DB and
# middleware stack as production.

pytestmark = pytest.mark.skipif(TEST_DATABASE_URL is None, reason="no test database configured")

N_MINUS_1 = "0.1.0"
N_CURRENT = "0.2.0"
BELOW_MINIMUM = "0.0.9"

FAMILIES = ("desktop", "daemon", "dashboard")


def _window_settings() -> Settings:
    return Settings(
        **{f"{family}_minimum_version": N_MINUS_1 for family in FAMILIES},
        **{f"{family}_latest_version": N_CURRENT for family in FAMILIES},
    )


def _headers(family: str, version: str) -> dict[str, str]:
    return {"X-Studio-Client": family, "X-Studio-Client-Version": version}


@pytest_asyncio.fixture
async def window_client(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    """A real API app whose version window is wider than the defaults, sharing
    the test's savepoint DB — the only way to observe an N-1 that is neither the
    current nor the floor build."""
    monkeypatch.setattr("studio_api.settings.get_settings", _window_settings)
    app = create_app()

    async def _override_get_session() -> AsyncSession:  # type: ignore[misc]
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)


async def _admin_with_password(db_session: AsyncSession, password: str = "secret123") -> str:
    email = f"matrix-{uuid.uuid4().hex[:8]}@example.test"
    user = await provisioning_service.create_user(db_session, "Matrix Admin", email, "admin")
    await provisioning_service.set_user_password(db_session, user.email, password)
    return email


async def test_n_minus_1_login_works_and_is_flagged_recommended(
    window_client: AsyncClient, db_session: AsyncSession
) -> None:
    email = await _admin_with_password(db_session)

    login = await window_client.post(
        "/api/v1/auth/token",
        json={"email": email, "password": "secret123"},
        headers=_headers("dashboard", N_MINUS_1),
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert token.count(".") == 2

    # An N-1 client inside the window is served, not blocked — only advised.
    assert login.headers["x-studio-client-update"] == "recommended"
    assert login.headers["x-studio-client-latest"] == N_CURRENT

    projects = await window_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}", **_headers("dashboard", N_MINUS_1)},
    )
    assert projects.status_code == 200


async def test_current_client_is_never_flagged(
    window_client: AsyncClient, db_session: AsyncSession
) -> None:
    email = await _admin_with_password(db_session)

    login = await window_client.post(
        "/api/v1/auth/token",
        json={"email": email, "password": "secret123"},
        headers=_headers("dashboard", N_CURRENT),
    )
    assert login.status_code == 200
    assert "x-studio-client-update" not in login.headers


async def test_below_minimum_is_refused_on_api_and_auth_surfaces(
    window_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # The guard runs before auth: even a valid credentialed call is refused,
    # with a machine-readable invitation to update.
    projects = await window_client.get(
        "/api/v1/projects", headers={**auth_headers, **_headers("daemon", BELOW_MINIMUM)}
    )
    assert projects.status_code == 426
    detail = projects.json()["detail"]
    assert detail["error_code"] == "client_upgrade_required"
    assert detail["minimum_supported"] == N_MINUS_1
    assert detail["latest"] == N_CURRENT

    login = await window_client.post(
        "/api/v1/auth/token",
        json={"email": "nobody@example.test", "password": "wrong"},
        headers=_headers("desktop", BELOW_MINIMUM),
    )
    assert login.status_code == 426
    assert login.json()["detail"]["error_code"] == "client_upgrade_required"


async def test_n_minus_1_session_flow_without_crash(
    window_client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    headers = {**auth_headers, **_headers("daemon", N_MINUS_1)}

    task = await window_client.post(
        "/api/v1/tasks", headers=headers, json={"project_id": str(project.id), "title": "N-1"}
    )
    assert task.status_code == 201
    assert task.headers["x-studio-client-update"] == "recommended"

    machine_model, _ = machine
    session = await window_client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"task_id": task.json()["id"], "machine_id": str(machine_model.id)},
    )
    assert session.status_code == 201
    ended = await window_client.patch(
        f"/api/v1/sessions/{session.json()['id']}/end", headers=headers
    )
    assert ended.status_code == 200


async def test_n_minus_1_filtered_list_hides_another_users_resource(
    window_client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    created = await window_client.post(
        "/api/v1/library",
        headers={**auth_headers, **_headers("dashboard", N_MINUS_1)},
        json={
            "kind": "skill",
            "stable_key": f"n1-private-{uuid.uuid4().hex[:8]}",
            "scope": "user",
            "title": "N-1 private skill",
            "content": {"content_schema": "studio.library.skill/v1", "text": "body"},
        },
    )
    assert created.status_code == 201

    listing = await window_client.get(
        "/api/v1/library", headers={**other_auth_headers, **_headers("dashboard", N_MINUS_1)}
    )
    assert listing.status_code == 200
    assert created.json()["id"] not in {item["id"] for item in listing.json()}


async def test_n_minus_1_forbidden_project_write_is_a_clean_403(
    window_client: AsyncClient,
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    response = await window_client.post(
        "/api/v1/tasks",
        headers={**readonly_auth_headers, **_headers("dashboard", N_MINUS_1)},
        json={"project_id": str(project.id), "title": "nope"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "forbidden"


async def test_sse_is_refused_for_a_below_minimum_client(window_client: AsyncClient) -> None:
    # The compatibility gate runs before the stream route: a below-minimum
    # client is answered immediately, never left hanging on a live stream.
    response = await window_client.get(
        "/api/v1/events/stream",
        params={"project": str(uuid.uuid4())},
        headers=_headers("dashboard", BELOW_MINIMUM),
    )
    assert response.status_code == 426
    assert response.json()["detail"]["error_code"] == "client_upgrade_required"


async def test_there_is_no_refresh_endpoint_so_login_is_reacquired(
    window_client: AsyncClient,
) -> None:
    # "refresh si applicable": it is not — tokens are re-obtained through
    # POST /auth/token; a supported N-1 client gets an ordinary 404 here, never
    # a compatibility refusal.
    response = await window_client.post(
        "/api/v1/auth/refresh", headers=_headers("dashboard", N_MINUS_1)
    )
    assert response.status_code == 404
