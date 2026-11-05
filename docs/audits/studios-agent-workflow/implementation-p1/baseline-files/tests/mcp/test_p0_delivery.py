from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_api.deps import resolve_machine
from studio_api.services import handoff as handoff_service
from studio_api.services import sync as sync_service
from studio_api.services.authz import load_principal
from studio_contracts.handoff import HandoffRequest
from studio_mcp.tools.coordination import studio_coordinate
from studio_mcp.tools.handoff import studio_handoff
from studio_mcp.tools.sessions import studio_start_session
from studio_mcp.tools.start_work import studio_start_work
from studio_mcp.tools.sync import studio_sync
from studio_mcp.tools.tasks import studio_create_task, studio_get_task

from tests.mcp.conftest import FakeContext


def dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def signals(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [item["coordination"] for item in block["items"] if item.get("coordination")]


@pytest.mark.parametrize("directed", [False, True])
@pytest.mark.parametrize("mode", ["unread", "presented", "acked", "late", "budget", "resync"])
async def test_compact_lost_handoff_response_recovers_content_in_successor(
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    project: ProjectModel,
    agent: AgentModel,
    monkeypatch: pytest.MonkeyPatch,
    directed: bool,
    mode: str,
) -> None:
    task = await studio_create_task(str(project.id), "recipient", auth_ctx)
    source_task = await studio_create_task(str(project.id), "sender", other_auth_ctx)
    source = await studio_start_session(source_task["id"], other_auth_ctx)
    first = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"]
    )
    session_id = first["session"]["id"]
    count = 6 if mode == "budget" else 3
    texts = [f"signal-{index}:" + "x" * 240 for index in range(count)]

    async def send(index: int) -> str:
        emitted = dump(await studio_coordinate(
            source["id"], "question", task["id"], texts[index], other_auth_ctx,
            session_id=session_id if directed else None,
        ))
        assert "error_code" not in emitted, emitted
        return emitted["event_id"]

    ids = [await send(index) for index in range(count - (mode == "late"))]
    if mode in {"presented", "acked", "late"}:
        received = dump(await studio_sync(auth_ctx, session_id=session_id))
        assert [signal["text"] for signal in signals(received)] == texts[:len(ids)]
        if mode in {"acked", "late"}:
            await studio_sync(auth_ctx, session_id=session_id, ack=received["next_cursor"])
    if mode == "late":
        ids.append(await send(count - 1))

    if mode == "resync":
        monkeypatch.setattr(sync_service, "SYNC_SCAN_CAP", 1)
    closed = await studio_handoff(
        str(project.id), session_id, auth_ctx,
        idempotency_key="p0-lost-response", coordination_text="next step",
    )
    assert "error_code" not in closed, closed
    assert "sync" not in closed
    assert len(json.dumps(closed, ensure_ascii=True)) <= 1000
    retry = await studio_handoff(
        str(project.id), session_id, auth_ctx,
        idempotency_key="p0-lost-response", coordination_text="next step",
    )
    assert retry == closed
    successor = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"]
    )
    assert successor["session"]["id"] != session_id
    new_id = successor["session"]["id"]
    expected = [] if mode == "acked" else ids[-1:] if mode == "late" else ids
    contents: dict[str, str] = {}
    order: list[str] = []
    effects: set[str] = set()
    for _ in range(20):
        block = dump(await studio_sync(
            auth_ctx, session_id=new_id, max_chars=1000 if mode == "budget" else 12000,
        ))
        repeated = dump(await studio_sync(
            auth_ctx, session_id=new_id, max_chars=1000 if mode == "budget" else 12000,
        ))
        assert repeated == block
        for signal in signals(block):
            if signal["event_id"] in ids:
                if signal["event_id"] not in effects:
                    effects.add(signal["event_id"])
                    order.append(signal["event_id"])
                contents[signal["event_id"]] = signal["text"]
        await studio_sync(auth_ctx, session_id=new_id, ack=block["next_cursor"])
        if not block["overflow"] and not block["resync"]:
            break
    assert order == expected
    assert contents == {event_id: texts[ids.index(event_id)] for event_id in expected}
    assert effects == set(expected)
    repeated_handoff = await studio_handoff(
        str(project.id), session_id, auth_ctx, coordination_text="next step"
    )
    assert repeated_handoff["coordination_event_id"] == closed["coordination_event_id"]
    final = dump(await studio_sync(auth_ctx, session_id=new_id))
    assert signals(final) == []


@pytest.mark.parametrize("after_end", [False, True])
async def test_handoff_interruption_between_commits_preserves_signal(
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    project: ProjectModel,
    agent: AgentModel,
    monkeypatch: pytest.MonkeyPatch,
    after_end: bool,
    db_session: AsyncSession,
) -> None:
    task = await studio_create_task(str(project.id), "interrupted recipient", auth_ctx)
    source_task = await studio_create_task(str(project.id), "sender", other_auth_ctx)
    source = await studio_start_session(source_task["id"], other_auth_ctx)
    first = await studio_start_work(str(project.id), str(agent.id), auth_ctx, task_id=task["id"])
    session_id = first["session"]["id"]
    emitted = dump(await studio_coordinate(
        source["id"], "heads_up", task["id"], "recover exact content", other_auth_ctx,
        session_id=session_id,
    ))
    original_end = handoff_service.sessions_service.end_session

    async def interrupted_end(*args: Any, **kwargs: Any) -> None:
        if after_end:
            await original_end(*args, **kwargs)
        raise RuntimeError("simulated crash between committed steps")

    with monkeypatch.context() as patch:
        patch.setattr(handoff_service.sessions_service, "end_session", interrupted_end)
        with pytest.raises(RuntimeError, match="simulated crash"):
            token = auth_ctx.headers["authorization"].removeprefix("Bearer ")
            machine = await resolve_machine(db_session, token)
            assert machine is not None
            principal = await load_principal(db_session, machine)
            await handoff_service.handoff(
                db_session, principal,
                HandoffRequest(project_id=project.id, session_id=session_id),
            )
    retry = await studio_handoff(str(project.id), session_id, auth_ctx)
    assert "error_code" not in retry, retry
    successor = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"]
    )
    block = dump(await studio_sync(auth_ctx, session_id=successor["session"]["id"]))
    assert {item["event_id"]: item["text"] for item in signals(block)} == {
        emitted["event_id"]: "recover exact content"
    }


async def test_completed_task_recovers_via_stateless_sync(
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    task = await studio_create_task(str(project.id), "completed recovery", auth_ctx)
    first = await studio_start_work(str(project.id), str(agent.id), auth_ctx, task_id=task["id"])
    sender_task = await studio_create_task(str(project.id), "sender", other_auth_ctx)
    sender = await studio_start_session(sender_task["id"], other_auth_ctx)
    sent = dump(await studio_coordinate(
        sender["id"], "question", task["id"], "recover after completion", other_auth_ctx,
        session_id=first["session"]["id"],
    ))
    current = await studio_get_task(task["id"], auth_ctx)
    closed = await studio_handoff(
        str(project.id), first["session"]["id"], auth_ctx,
        task_status="completed", expected_version=current["version"],
    )
    assert closed["task_status"] == "completed"
    recovered = dump(await studio_sync(
        auth_ctx, agent_id=str(agent.id), task_id=task["id"],
        ack=closed["handoff_cursor_seq"],
    ))
    assert {item["event_id"]: item["text"] for item in signals(recovered)} == {
        sent["event_id"]: "recover after completion"
    }
