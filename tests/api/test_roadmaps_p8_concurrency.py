"""Roadmaps P8 on real cross-transaction races (separate Postgres connections):
concurrent reviewers of one proposal and concurrent proposals. The roadmap row lock
must leave exactly one winner and a consistent revision history."""

from __future__ import annotations

import asyncio

from httpx import AsyncClient
from studio_api.db.models.project import ProjectModel

from tests.api.test_roadmaps_domain import race, real_engine  # noqa: F401
from tests.api.test_roadmaps_p8 import active_roadmap, document, propose, review


async def _revisions(
    client: AsyncClient, headers: dict[str, str], roadmap_id: str, **params: str
) -> list[dict[str, object]]:
    response = await client.get(
        f"/api/v1/roadmaps/{roadmap_id}/revisions", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_concurrent_approvals_of_one_proposal_exactly_one_wins(
    race: tuple[AsyncClient, dict[str, str], ProjectModel],  # noqa: F811
) -> None:
    client, headers, project = race
    active = await active_roadmap(client, headers, project)
    proposal = (await propose(client, headers, active, document(title="Renamed"))).json()

    responses = await asyncio.gather(
        *(review(client, headers, active, proposal["revision_no"], "approve") for _ in range(3))
    )

    assert sorted(r.status_code for r in responses) == [200, 409, 409]
    winner = next(r for r in responses if r.status_code == 200).json()
    assert winner["approved_revision_no"] == proposal["revision_no"]
    approved = await _revisions(client, headers, active["id"], status="approved")
    assert [r["revision_no"] for r in approved] == [proposal["revision_no"]]


async def test_an_approval_racing_a_rejection_leaves_one_consistent_outcome(
    race: tuple[AsyncClient, dict[str, str], ProjectModel],  # noqa: F811
) -> None:
    client, headers, project = race
    active = await active_roadmap(client, headers, project)
    proposal = (await propose(client, headers, active, document(title="Renamed"))).json()
    number = proposal["revision_no"]

    approve, reject = await asyncio.gather(
        review(client, headers, active, number, "approve"),
        review(client, headers, active, number, "reject", comment="not now"),
    )

    assert sorted([approve.status_code, reject.status_code]) == [200, 409]
    settled = {
        r["revision_no"]: r["status"]
        for r in await _revisions(client, headers, active["id"], kind="proposal")
    }
    expected = "approved" if approve.status_code == 200 else "rejected"
    assert settled[number] == expected
    current = await client.get(f"/api/v1/roadmaps/{active['id']}", headers=headers)
    applied = current.json()["approved_revision_no"] == number
    assert applied is (approve.status_code == 200)


async def test_concurrent_proposals_keep_distinct_numbers_and_a_single_pending_one(
    race: tuple[AsyncClient, dict[str, str], ProjectModel],  # noqa: F811
) -> None:
    client, headers, project = race
    active = await active_roadmap(client, headers, project)

    responses = await asyncio.gather(
        *(
            propose(client, headers, active, document(title=f"Idea {n}"), summary=f"idea {n}")
            for n in range(4)
        )
    )

    numbers = [r.json()["revision_no"] for r in responses]
    assert len(set(numbers)) == 4
    pending = await _revisions(client, headers, active["id"], status="pending")
    assert len(pending) == 1
    superseded = await _revisions(client, headers, active["id"], status="superseded")
    assert len(superseded) == 3
    current = await client.get(f"/api/v1/roadmaps/{active['id']}", headers=headers)
    assert current.json()["approved_revision_no"] == active["approved_revision_no"]
