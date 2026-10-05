from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from studio_client.config import ClientConfig
from studio_client.daemon.service import BridgeService, DaemonController, serve_streams
from studio_client.tokens import MemoryTokenStore
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.handshake import HandshakeRequest


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None

ORIGIN = "https://studio.example"
SESSION = "e2e.human-session.SESSIONSECRET0123"
MACHINE_NAME = "Studi'OS Desktop · Café 😀 — 2026-09-28"


class EchoService:
    def handle_line(self, line: str) -> dict[str, Any]:
        return {"kind": "response", "echo": json.loads(line)["payload"]["machine_name"]}


def utf8_line(payload: dict[str, Any]) -> bytes:
    line = json.dumps(
        {
            "kind": "request",
            "protocol": "studio.local/v1",
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-28T00:00:00Z",
            "command": "identity.enroll",
            "payload": payload,
        },
        ensure_ascii=False,
    )
    return (line + "\n").encode("utf-8")


def cp1252_stream(raw: bytes) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(raw), encoding="cp1252")


def test_stdio_preserves_middle_dot_accent_and_emoji() -> None:
    raw = utf8_line({"machine_name": MACHINE_NAME})
    source = cp1252_stream(raw)
    destination = io.StringIO()
    serve_streams(EchoService(), source, destination)  # type: ignore[arg-type]
    answer = json.loads(destination.getvalue().splitlines()[0])
    assert answer["echo"] == MACHINE_NAME
    assert "Â" not in answer["echo"]
    assert "Ã" not in answer["echo"]


def test_enroll_posts_exact_non_ascii_display_name(tmp_path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["display_name"])
        now = datetime.now(UTC).isoformat()
        machine_id = uuid4()
        user_id = uuid4()
        return httpx.Response(
            201,
            json={
                "id": str(machine_id),
                "owner_user_id": str(user_id),
                "display_name": seen[-1],
                "status": "offline",
                "credential": "machine-credential-CREDSECRET0123456789",
                "version": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

    controller = DaemonController(
        ClientConfig(api_base_url=ORIGIN, profile_id="main", machine_id=uuid4()),
        data_root=tmp_path,
        token_store=MemoryTokenStore(),
        enroll_transport=httpx.MockTransport(handler),
    )
    service = BridgeService(controller)
    handshake = HandshakeRequest.model_validate(
        {
            "peer": {
                "role": "desktop",
                "protocol": {"minimum": {"major": 1, "minor": 0}, "maximum": {"major": 1, "minor": 0}},
                "component_version": "0.1.0",
                "capabilities": ["daemon.control", "identity.view", "identity.enroll"],
                "required_capabilities": ["daemon.control"],
            }
        }
    )
    enroll_payload = {
        "profile": {"profile_id": "main", "server_origin": ORIGIN},
        "human_session": SESSION,
        "machine_name": MACHINE_NAME,
    }
    handshake_line = BridgeRequest.model_validate(
        {
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-28T00:00:00Z",
            "command": "runtime.handshake",
            "payload": handshake.model_dump(mode="json"),
        }
    ).model_dump_json()
    enroll_line = BridgeRequest.model_validate(
        {
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-28T00:00:00Z",
            "command": "identity.enroll",
            "payload": enroll_payload,
        }
    ).model_dump_json()
    raw = ((handshake_line + "\n") + (enroll_line + "\n")).encode("utf-8")
    source = cp1252_stream(raw)
    destination = io.StringIO()
    serve_streams(service, source, destination)
    assert seen == [MACHINE_NAME]
