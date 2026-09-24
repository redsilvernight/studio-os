from __future__ import annotations

import json
from io import StringIO
from uuid import uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.daemon.service import (
    BridgeService,
    DaemonController,
    SharedBridgeService,
    serve_streams,
)
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.daemon_control import (
    DaemonAction,
    DaemonControlRequest,
    DaemonHealthRequest,
)
from studio_contracts.local.handshake import HandshakeRequest
from studio_contracts.local.identity import ProfileRef


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


def controller(tmp_path) -> DaemonController:
    return DaemonController(
        ClientConfig(
            api_base_url="https://studio.example/api/v1",
            profile_id="main",
            machine_id=uuid4(),
        ),
        data_root=tmp_path,
    )


def request(command: str, payload: dict) -> str:
    value = BridgeRequest.model_validate(
        {
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-21T00:00:00Z",
            "command": command,
            "payload": payload,
        }
    )
    return value.model_dump_json()


def negotiate(service: BridgeService | SharedBridgeService, capabilities: list[str]):
    payload = HandshakeRequest.model_validate(
        {
            "peer": {
                "role": "desktop",
                "protocol": {
                    "minimum": {"major": 1, "minor": 0},
                    "maximum": {"major": 1, "minor": 0},
                },
                "component_version": "0.1.0",
                "capabilities": capabilities,
                "required_capabilities": ["daemon.control"],
            }
        }
    )
    return service.handle_line(request("runtime.handshake", payload.model_dump(mode="json")))


def test_handshake_advertises_health_capability(tmp_path) -> None:
    service = BridgeService(controller(tmp_path))
    answer = negotiate(service, ["daemon.control", "daemon.health", "identity.view"])

    assert answer["payload"]["outcome"] == "compatible"
    assert "daemon.health" in answer["payload"]["daemon"]["capabilities"]


def test_status_is_stopped_before_start(tmp_path) -> None:
    daemon = controller(tmp_path)
    service = BridgeService(daemon)
    negotiate(service, ["daemon.control"])
    profile = ProfileRef(profile_id="main", server_origin="https://studio.example")
    control = DaemonControlRequest(action=DaemonAction.STATUS, profile=profile)

    answer = service.handle_line(request("daemon.status", control.model_dump(mode="json")))

    assert answer["payload"]["outcome"] == "ok"
    assert answer["payload"]["status"]["state"] == "stopped"


def test_profile_mismatch_is_fail_closed(tmp_path) -> None:
    daemon = controller(tmp_path)
    service = BridgeService(daemon)
    negotiate(service, ["daemon.control"])
    control = DaemonControlRequest(
        action=DaemonAction.START,
        profile=ProfileRef(profile_id="other", server_origin="https://studio.example"),
    )

    answer = service.handle_line(request("daemon.start", control.model_dump(mode="json")))

    assert answer["payload"]["outcome"] == "identity_mismatch"
    assert answer["payload"]["error"]["code"] == "identity_mismatch"


def test_start_without_enrolled_machine_is_refused_not_raised(tmp_path) -> None:
    daemon = DaemonController(
        ClientConfig(api_base_url="https://studio.example/api/v1", profile_id="main"),
        data_root=tmp_path,
    )
    control = DaemonControlRequest(action=DaemonAction.START, profile=daemon._profile())

    result = daemon.control(control)

    assert result.outcome == "unavailable"
    assert result.error is not None and result.error.code == "daemon_unavailable"
    assert result.status.state == "stopped"


def test_stale_expected_instance_is_refused_before_control(tmp_path) -> None:
    daemon = controller(tmp_path)
    service = BridgeService(daemon)
    negotiate(service, ["daemon.control"])
    control = DaemonControlRequest(
        action=DaemonAction.STOP,
        profile=ProfileRef(profile_id="main", server_origin="https://studio.example"),
        expected_instance_id=uuid4(),
    )

    answer = service.handle_line(request("daemon.stop", control.model_dump(mode="json")))

    assert answer["payload"]["outcome"] == "failed"
    assert answer["payload"]["error"]["code"] == "invalid_request"


def test_stream_protocol_emits_one_bounded_json_answer_per_line(tmp_path) -> None:
    service = BridgeService(controller(tmp_path))
    negotiate(service, ["daemon.control"])
    profile = ProfileRef(profile_id="main", server_origin="https://studio.example")
    control = DaemonControlRequest(action=DaemonAction.STATUS, profile=profile)
    source = StringIO(request("daemon.status", control.model_dump(mode="json")) + "\n")
    destination = StringIO()

    serve_streams(service, source, destination)

    lines = destination.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["payload"]["status"]["state"] == "stopped"


def test_second_desktop_proxies_to_existing_control_endpoint(tmp_path) -> None:
    owner = SharedBridgeService(controller(tmp_path))
    attached = SharedBridgeService(controller(tmp_path))
    profile = ProfileRef(profile_id="main", server_origin="https://studio.example")
    control = DaemonControlRequest(action=DaemonAction.STATUS, profile=profile)

    try:
        negotiate(attached, ["daemon.control"])
        answer = attached.handle_line(request("daemon.status", control.model_dump(mode="json")))
    finally:
        attached.close(persist=False)
        owner.close(persist=False)

    assert answer["payload"]["status"]["state"] == "stopped"


def test_health_is_refused_before_handshake(tmp_path) -> None:
    service = BridgeService(controller(tmp_path))
    health = DaemonHealthRequest(
        profile=ProfileRef(profile_id="main", server_origin="https://studio.example")
    )

    answer = service.handle_line(request("daemon.health", health.model_dump(mode="json")))

    assert answer["kind"] == "error"
    assert answer["error"]["code"] == "capability_missing"


def test_health_is_refused_when_handshake_did_not_grant_it(tmp_path) -> None:
    service = BridgeService(controller(tmp_path))
    negotiate(service, ["daemon.control"])
    health = DaemonHealthRequest(
        profile=ProfileRef(profile_id="main", server_origin="https://studio.example")
    )

    answer = service.handle_line(request("daemon.health", health.model_dump(mode="json")))

    assert answer["error"]["code"] == "capability_missing"


def test_health_is_available_after_capability_is_granted(tmp_path) -> None:
    service = BridgeService(controller(tmp_path))
    negotiate(service, ["daemon.control", "daemon.health"])
    health = DaemonHealthRequest(
        profile=ProfileRef(profile_id="main", server_origin="https://studio.example")
    )

    answer = service.handle_line(request("daemon.health", health.model_dump(mode="json")))

    assert answer["kind"] == "response"
    assert answer["payload"]["status"]["state"] == "stopped"
