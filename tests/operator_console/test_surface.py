from __future__ import annotations

from httpx import AsyncClient
from studio_operator.main import app

# The complete surface of the console. Equality (not containment) is the point:
# any new route — and therefore any new read of client data — fails this test
# until it is deliberately added here and reviewed against the mockups.
EXPECTED_API_ROUTES = {
    ("/api/v1/auth/mfa", "POST"),
    ("/api/v1/auth/enrollment", "POST"),
    ("/api/v1/auth/enrollment/confirm", "POST"),
    ("/api/v1/auth/me", "GET"),
    ("/api/v1/auth/logout", "POST"),
    ("/api/v1/dashboard", "GET"),
    ("/api/v1/measures", "GET"),
    ("/api/v1/studios", "GET"),
    ("/api/v1/studios/{studio_id}", "GET"),
    ("/api/v1/studios/{studio_id}/suspension", "POST"),
    ("/api/v1/studios/{studio_id}/suspension", "DELETE"),
    ("/api/v1/usage", "GET"),
    ("/api/v1/billing", "GET"),
    ("/api/v1/suspensions", "GET"),
    ("/api/v1/break-glass", "GET"),
}

FORBIDDEN_SEGMENTS = (
    "project",
    "file",
    "note",
    "message",
    "transfer",
    "vault",
    "content",
    "task",
    "roadmap",
    "decision",
)


def test_the_surface_is_exactly_the_aggregate_console() -> None:
    # The OpenAPI schema is the public, authoritative list of what the console
    # answers — including the mounted static front being absent from it.
    schema = app.openapi()
    routes = {
        (path, method.upper())
        for path, operations in schema["paths"].items()
        if path.startswith("/api/v1")
        for method in operations
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    assert routes == EXPECTED_API_ROUTES


def test_no_route_even_mentions_client_content() -> None:
    for path, _method in EXPECTED_API_ROUTES:
        for segment in FORBIDDEN_SEGMENTS:
            assert segment not in path, f"{path} exposes a content-ish resource ({segment})"


async def test_aggregate_routes_refuse_anonymous_callers(client: AsyncClient) -> None:
    for path in (
        "/api/v1/dashboard",
        "/api/v1/measures",
        "/api/v1/studios",
        "/api/v1/usage",
        "/api/v1/billing",
        "/api/v1/suspensions",
        "/api/v1/break-glass",
    ):
        response = await client.get(path)
        assert response.status_code == 401, path
        assert response.json() == {"detail": "Not authenticated"}


async def test_only_the_probes_are_public(client: AsyncClient) -> None:
    for path in ("/healthz", "/readyz"):
        response = await client.get(path)
        assert response.status_code == 200, path
        assert response.json()["status"] in {"ok", "ready"}


async def test_suspension_write_is_authenticated_too(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/studios/11111111-1111-1111-1111-111111111111/suspension",
        json={"reason": "motif"},
    )
    assert response.status_code == 401


async def test_the_static_front_is_served_from_the_same_origin(client: AsyncClient) -> None:
    page = await client.get("/")
    assert page.status_code == 200
    assert "Console opérateur" in page.text
    assert "app.js" in page.text
