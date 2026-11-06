from __future__ import annotations

import pytest
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.coordination import studio_coordinate
from studio_mcp.tools.handoff import studio_handoff
from studio_mcp.tools.sessions import studio_start_session
from studio_mcp.tools.start_work import studio_start_work
from studio_mcp.tools.sync import studio_sync
from studio_mcp.tools.tasks import studio_create_task

from tests.mcp.conftest import FakeContext
from tests.mcp.test_p0_delivery import dump, signals


@pytest.mark.parametrize("self_emitted", [False, True])
async def test_live_peer_ack_cannot_hide_a_directed_signal_from_successor(
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    project: ProjectModel,
    agent: AgentModel,
    self_emitted: bool,
) -> None:
    task = await studio_create_task(str(project.id), "shared recipient", auth_ctx)
    sender_task = await studio_create_task(str(project.id), "separate sender", auth_ctx)
    a = await studio_start_session(task["id"], auth_ctx)
    b = await studio_start_session(task["id"], other_auth_ctx)
    sender = await studio_start_session(sender_task["id"], auth_ctx)
    directed = dump(
        await studio_coordinate(
            b["id"] if self_emitted else sender["id"],
            "question",
            task["id"],
            "content exclusively delivered to A",
            other_auth_ctx if self_emitted else auth_ctx,
            session_id=a["id"],
        )
    )
    marker = dump(
        await studio_coordinate(
            sender["id"],
            "heads_up",
            task["id"],
            "later broadcast processed by B",
            auth_ctx,
        )
    )
    assert "error_code" not in directed, directed
    assert "error_code" not in marker, marker
    pulled_by_b = dump(await studio_sync(other_auth_ctx, session_id=b["id"]))
    assert [signal["event_id"] for signal in signals(pulled_by_b)] == [marker["event_id"]]
    assert pulled_by_b["overflow"]["coordination"] == 1
    await studio_sync(other_auth_ctx, session_id=b["id"], ack=pulled_by_b["next_cursor"])
    for session_id, context in ((b["id"], other_auth_ctx), (a["id"], auth_ctx)):
        closed = await studio_handoff(str(project.id), session_id, context)
        assert "error_code" not in closed, closed
    successor = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"]
    )
    assert "error_code" not in successor, successor
    recovered = dump(await studio_sync(auth_ctx, session_id=successor["session"]["id"]))
    assert {signal["event_id"]: signal["text"] for signal in signals(recovered)}.get(
        directed["event_id"]
    ) == "content exclusively delivered to A"


async def test_target_ack_releases_the_live_peer_cursor(
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    project: ProjectModel,
) -> None:
    task = await studio_create_task(str(project.id), "live target ack", auth_ctx)
    a = await studio_start_session(task["id"], auth_ctx)
    b = await studio_start_session(task["id"], other_auth_ctx)
    sent = dump(
        await studio_coordinate(
            b["id"],
            "question",
            task["id"],
            "ack releases floor",
            other_auth_ctx,
            session_id=a["id"],
        )
    )
    blocked = dump(await studio_sync(other_auth_ctx, session_id=b["id"]))
    assert blocked["overflow"] == {"coordination": 1}
    received = dump(await studio_sync(auth_ctx, session_id=a["id"]))
    assert [item["event_id"] for item in signals(received)] == [sent["event_id"]]
    await studio_sync(auth_ctx, session_id=a["id"], ack=received["next_cursor"])
    released = dump(await studio_sync(other_auth_ctx, session_id=b["id"]))
    assert released["overflow"] == {}
