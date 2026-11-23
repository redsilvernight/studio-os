from __future__ import annotations

from httpx import AsyncClient

from tests.operator_console.fakes import ATELIER, INTERNAL, FakeRepository


async def test_the_directory_lists_studios_with_aggregate_measures(
    client: AsyncClient, repository: FakeRepository, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/studios", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    first = body["studios"][0]
    assert set(first) == {
        "id",
        "name",
        "slug",
        "plan",
        "status",
        "suspension_reason",
        "created_at",
        "owner_email",
        "storage",
        "members",
        "members_limit",
    }
    # Quotas come from server configuration (illustrative values, DEC-0387).
    assert first["storage"]["quota_bytes"] == 2 * 1024**3
    assert first["members_limit"] == 5
    assert first["storage"]["percent"] == 90.0


async def test_search_matches_name_slug_or_owner_address(
    client: AsyncClient, repository: FakeRepository, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/studios", params={"q": "Binaweb"}, headers=auth_headers)
    assert response.status_code == 200
    assert [studio["name"] for studio in response.json()["studios"]] == ["Binaweb"]
    assert repository.queries[-1] == "Binaweb"

    owner = await client.get("/api/v1/studios", params={"q": "flo@"}, headers=auth_headers)
    assert owner.status_code == 200
    assert {studio["name"] for studio in owner.json()["studios"]} == {
        "Atelier Phare",
        "Binaweb",
    }


async def test_the_studio_sheet_is_measures_only(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(f"/api/v1/studios/{ATELIER}", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["studio"]["name"] == "Atelier Phare"
    assert body["studio"]["owner_email"] == "flo@example.test"
    assert body["usage_window_days"] == 30
    assert body["usage"]["tokens_in"] == 1200
    assert "projects" not in body
    assert "files" not in body


async def test_an_unknown_studio_is_a_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/studios/33333333-3333-3333-3333-333333333333", headers=auth_headers
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "studio_not_found"


async def test_suspension_requires_a_motif(
    client: AsyncClient, repository: FakeRepository, auth_headers: dict[str, str]
) -> None:
    for reason in ("", "ab"):
        response = await client.post(
            f"/api/v1/studios/{ATELIER}/suspension",
            json={"reason": reason},
            headers=auth_headers,
        )
        assert response.status_code == 422, reason
    assert repository.writes == []


async def test_suspension_writes_only_the_studio_status(
    client: AsyncClient, repository: FakeRepository, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"/api/v1/studios/{ATELIER}/suspension",
        json={"reason": "Paiement non régularisé depuis 21 jours"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "suspended"
    assert response.json()["suspension_reason"] == "Paiement non régularisé depuis 21 jours"
    assert repository.writes == [(ATELIER, "suspended", "Paiement non régularisé depuis 21 jours")]


async def test_the_internal_studio_cannot_be_suspended(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"/api/v1/studios/{INTERNAL}/suspension",
        json={"reason": "Contrôle"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "studio_not_suspendable"


async def test_suspending_an_unknown_studio_is_a_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/studios/33333333-3333-3333-3333-333333333333/suspension",
        json={"reason": "Contrôle"},
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_lifting_a_suspension_on_the_internal_studio_is_refused(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.delete(f"/api/v1/studios/{INTERNAL}/suspension", headers=auth_headers)
    # The fake refuses the internal studio on any status write, like the SQL repo.
    assert response.status_code == 409


async def test_suspended_studios_are_listed(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    suspended = await client.get("/api/v1/suspensions", headers=auth_headers)
    assert suspended.status_code == 200
    body = suspended.json()
    assert body["total"] == 1
    studio = body["studios"][0]
    assert studio["name"] == "Studio OS"
    assert studio["since"] is not None
    assert studio["suspension_reason"] == "Impayé depuis 21 jours"


async def test_reactivation_of_a_suspendable_studio(
    client: AsyncClient, repository: FakeRepository, auth_headers: dict[str, str]
) -> None:
    await client.post(
        f"/api/v1/studios/{ATELIER}/suspension",
        json={"reason": "Contrôle"},
        headers=auth_headers,
    )
    response = await client.delete(f"/api/v1/studios/{ATELIER}/suspension", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    assert response.json()["suspension_reason"] is None
    assert repository.writes[-1] == (ATELIER, "active", None)
