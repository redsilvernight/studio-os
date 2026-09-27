"""A5 self-service enrollment through the daemon (`identity.enroll`, DEC-0130):
the session is used for one POST /machines toward the daemon's own server,
the credential lands in the keyring, and neither ever shows up in an answer
or a log line."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from studio_client.config import ClientConfig
from studio_client.daemon.service import BridgeService, DaemonController
from studio_client.tokens import MemoryTokenStore
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.handshake import HandshakeRequest

ORIGIN = "https://studio.example"
SESSION = "e2e.human-session.SESSIONSECRET0123"
CREDENTIAL = "machine-credential-CREDSECRET0123456789"
MACHINE_ID = uuid4()
USER_ID = uuid4()


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


class FakeServer:
    def __init__(self, status: int = 201, *, fail: bool = False) -> None:
        self.status = status
        self.fail = fail
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail:
            raise httpx.ConnectError("refused", request=request)
        if self.status != 201:
            return httpx.Response(self.status, json={"detail": "invalid or revoked token"})
        now = datetime.now(UTC).isoformat()
        return httpx.Response(
            201,
            json={
                "id": str(MACHINE_ID),
                "owner_user_id": str(USER_ID),
                "display_name": json.loads(request.content)["display_name"],
                "status": "offline",
                "credential": CREDENTIAL,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            },
        )


class BrokenStore(MemoryTokenStore):
    def set_token(self, origin: str, token: str) -> None:
        raise RuntimeError("keyring locked")


def service(
    tmp_path: Any, server: FakeServer, store: MemoryTokenStore | None = None
) -> tuple[BridgeService, MemoryTokenStore]:
    store = store if store is not None else MemoryTokenStore()
    controller = DaemonController(
        ClientConfig(api_base_url=ORIGIN, profile_id="main", machine_id=uuid4()),
        data_root=tmp_path,
        token_store=store,
        enroll_transport=httpx.MockTransport(server),
    )
    bridge = BridgeService(controller)
    handshake = HandshakeRequest.model_validate(
        {
            "peer": {
                "role": "desktop",
                "protocol": {
                    "minimum": {"major": 1, "minor": 0},
                    "maximum": {"major": 1, "minor": 0},
                },
                "component_version": "0.1.0",
                "capabilities": ["daemon.control", "identity.view", "identity.enroll"],
                "required_capabilities": ["daemon.control"],
            }
        }
    )
    bridge.handle_line(line("runtime.handshake", handshake.model_dump(mode="json")))
    return bridge, store


def line(command: str, payload: dict[str, Any]) -> str:
    return BridgeRequest.model_validate(
        {
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-26T00:00:00Z",
            "command": command,
            "payload": payload,
        }
    ).model_dump_json()


def enroll(origin: str = ORIGIN, **extra: Any) -> str:
    return line(
        "identity.enroll",
        {
            "profile": {"profile_id": "main", "server_origin": origin},
            "human_session": SESSION,
            "machine_name": "ADA-LAPTOP · Desktop",
            **extra,
        },
    )


def assert_no_secret(answer: dict[str, Any]) -> None:
    text = json.dumps(answer)
    assert "SESSIONSECRET" not in text
    assert "CREDSECRET" not in text


def test_enrolls_with_one_call_and_stores_the_credential(tmp_path) -> None:
    server = FakeServer()
    bridge, store = service(tmp_path, server)
    answer = bridge.handle_line(enroll())

    assert answer["kind"] == "response", answer
    assert answer["payload"]["outcome"] == "enrolled"
    assert answer["payload"]["machine_id"] == str(MACHINE_ID)
    assert answer["payload"]["view"]["secrets"][0]["status"] == "present"
    assert store.get_token(ORIGIN) == CREDENTIAL
    assert len(server.calls) == 1
    call = server.calls[0]
    assert (call.method, str(call.url)) == ("POST", f"{ORIGIN}/api/v1/machines")
    assert call.headers["authorization"] == f"Bearer {SESSION}"
    assert json.loads(call.content) == {"display_name": "ADA-LAPTOP · Desktop"}
    assert_no_secret(answer)


def test_an_enrolled_machine_is_not_enrolled_twice(tmp_path) -> None:
    server = FakeServer()
    store = MemoryTokenStore()
    store.set_token(ORIGIN, "existing-credential")
    bridge, _ = service(tmp_path, server, store)
    answer = bridge.handle_line(enroll())

    assert answer["payload"]["outcome"] == "already_enrolled"
    assert answer["payload"]["machine_id"] is None
    assert server.calls == []
    assert store.get_token(ORIGIN) == "existing-credential"


def test_replacing_an_existing_credential_is_explicit(tmp_path) -> None:
    server = FakeServer()
    store = MemoryTokenStore()
    store.set_token(ORIGIN, "revoked-credential")
    bridge, _ = service(tmp_path, server, store)
    answer = bridge.handle_line(enroll(replace_existing=True))

    assert answer["payload"]["outcome"] == "enrolled"
    assert store.get_token(ORIGIN) == CREDENTIAL


def test_a_session_for_another_server_never_leaves(tmp_path) -> None:
    server = FakeServer()
    bridge, store = service(tmp_path, server)
    answer = bridge.handle_line(enroll(origin="https://elsewhere.example"))

    assert answer["kind"] == "error"
    assert answer["error"]["code"] == "wrong_profile"
    assert server.calls == []
    assert store.get_token(ORIGIN) is None
    assert_no_secret(answer)


@pytest.mark.parametrize(
    ("status", "code", "reason"),
    [
        (401, "permission_denied", "session_expired"),
        (403, "permission_denied", "forbidden"),
        (500, "internal_error", "server_refused"),
    ],
)
def test_refusals_are_fixed_and_store_nothing(tmp_path, status, code, reason) -> None:
    bridge, store = service(tmp_path, FakeServer(status))
    answer = bridge.handle_line(enroll())

    assert answer["kind"] == "error"
    assert answer["error"]["code"] == code
    assert answer["error"]["details"] == {"reason": reason}
    assert "revoked token" not in answer["error"]["message"]
    assert store.get_token(ORIGIN) is None
    assert_no_secret(answer)


def test_unreachable_server_is_retryable(tmp_path) -> None:
    bridge, _ = service(tmp_path, FakeServer(fail=True))
    answer = bridge.handle_line(enroll())

    assert answer["error"]["code"] == "internal_error"
    assert answer["error"]["retryable"] is True
    assert answer["error"]["details"] == {"reason": "server_unreachable"}


def test_keyring_failure_after_creation_says_what_to_do(tmp_path) -> None:
    bridge, _ = service(tmp_path, FakeServer(), BrokenStore())
    answer = bridge.handle_line(enroll())

    assert answer["error"]["code"] == "keyring_unavailable"
    assert "revoke it" in answer["error"]["message"]
    assert answer["error"]["details"] == {"reason": "credential_not_stored"}
    assert_no_secret(answer)


def test_an_invalid_session_is_refused_without_echo(tmp_path) -> None:
    server = FakeServer()
    bridge, _ = service(tmp_path, server)
    bad = line(
        "identity.enroll",
        {
            "profile": {"profile_id": "main", "server_origin": ORIGIN},
            "human_session": SESSION,
            "machine_name": "ADA",
        },
    ).replace(SESSION, "SESSIONSECRET with spaces")
    answer = bridge.handle_line(bad)

    assert answer["error"]["code"] == "invalid_request"
    assert server.calls == []
    assert_no_secret(answer)


def test_enroll_needs_its_negotiated_capability(tmp_path) -> None:
    server = FakeServer()
    controller = DaemonController(
        ClientConfig(api_base_url=ORIGIN, profile_id="main", machine_id=uuid4()),
        data_root=tmp_path,
        token_store=MemoryTokenStore(),
        enroll_transport=httpx.MockTransport(server),
    )
    answer = BridgeService(controller).handle_line(enroll())

    assert answer["error"]["code"] == "capability_missing"
    assert server.calls == []


def test_neither_session_nor_credential_is_ever_logged(tmp_path, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    for server in (FakeServer(), FakeServer(401), FakeServer(fail=True)):
        bridge, _ = service(tmp_path, server)
        bridge.handle_line(enroll())
    logged = "\n".join(
        f"{record.getMessage()} {record.exc_text or ''}" for record in caplog.records
    )
    assert "SESSIONSECRET" not in logged
    assert "CREDSECRET" not in logged
