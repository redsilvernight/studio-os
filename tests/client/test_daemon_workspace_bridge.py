"""P11: the daemon serves the P1 `workspace.*` commands over the bridge."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.daemon.service import BridgeService, DaemonController
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.handshake import HandshakeRequest
from studio_contracts.local.identity import ProfileRef
from studio_workspaces import RootConfirmationService, WorkspaceBridge

WS = UUID("11111111-1111-4111-8111-111111111111")
PROFILE = ProfileRef(profile_id="main", server_origin="https://studio.example")
PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


def controller(tmp_path, bridge=True) -> DaemonController:
    return DaemonController(
        ClientConfig(
            api_base_url="https://studio.example/api/v1",
            profile_id="main",
            machine_id=uuid4(),
        ),
        data_root=tmp_path,
        workspace_bridge=WorkspaceBridge(tmp_path, RootConfirmationService()) if bridge else None,
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


def negotiate(service: BridgeService):
    payload = HandshakeRequest.model_validate(
        {
            "peer": {
                "role": "desktop",
                "protocol": {
                    "minimum": {"major": 1, "minor": 0},
                    "maximum": {"major": 1, "minor": 0},
                },
                "component_version": "0.1.0",
                "capabilities": ["daemon.control", "workspace.config"],
                "required_capabilities": ["daemon.control"],
            }
        }
    )
    return service.handle_line(request("runtime.handshake", payload.model_dump(mode="json")))


def answer_payload(answer: dict) -> dict:
    assert answer["kind"] == "response", answer
    return answer["payload"]


def test_handshake_grants_workspace_config(tmp_path) -> None:
    service = BridgeService(controller(tmp_path))
    answer = negotiate(service)
    assert answer["payload"]["outcome"] == "compatible"
    assert "workspace.config" in answer["payload"]["granted_capabilities"]


# The exact offer list of the Desktop peer (desktop/src-tauri/src/info.rs).
# If info.rs stops offering workspace.config, negotiation can never grant it
# and every workspace.* call fails end to end: this pins the parity.
DESKTOP_P11_OFFER = [
    "daemon.control",
    "identity.view",
    "daemon.health",
    "knowledge.read",
    "knowledge.graph",
    "knowledge.index",
    "code_graph.read",
    "code_graph.graph",
    "code_graph.index",
    "harness.read",
    "harness.plan",
    "harness.apply",
    "workspace.config",
]


def test_realistic_desktop_peer_is_granted_workspace_config(tmp_path) -> None:
    service = BridgeService(controller(tmp_path))
    payload = HandshakeRequest.model_validate(
        {
            "peer": {
                "role": "desktop",
                "protocol": {
                    "minimum": {"major": 1, "minor": 0},
                    "maximum": {"major": 1, "minor": 0},
                },
                "component_version": "0.1.0",
                "capabilities": DESKTOP_P11_OFFER,
                "required_capabilities": ["daemon.control", "identity.view"],
            }
        }
    )
    answer = service.handle_line(request("runtime.handshake", payload.model_dump(mode="json")))
    assert answer["payload"]["outcome"] == "compatible"
    granted = answer["payload"]["granted_capabilities"]
    assert "workspace.config" in granted
    for capability in ("daemon.control", "daemon.health", "identity.view"):
        assert capability in granted
    # This controller hosts no local features: knowledge/harness stay
    # ungranted by design (compatible_degraded path), workspace must not.
    assert "knowledge.read" not in granted
    assert "harness.read" not in granted


def test_full_first_association_over_the_bridge(tmp_path) -> None:
    folder = tmp_path / "game"
    folder.mkdir()
    service = BridgeService(controller(tmp_path))
    negotiate(service)

    missing = answer_payload(
        service.handle_line(request("workspace.validate", {"workspace_id": str(WS)}))
    )
    assert missing["health"] == "config_missing"

    confirmed = answer_payload(
        service.handle_line(
            request(
                "workspace.confirm_roots",
                {"roots": {"workspace_root": str(folder), "repo_roots": []}},
            )
        )
    )
    assert confirmed["root_confirmation_id"].startswith("rc-")

    config = {
        "schema_version": 1,
        "workspace_id": str(WS),
        "profile": {"profile_id": "main", "server_origin": "https://studio.example"},
        "project_id": str(PROJECT_ID),
        "project_slug": "demo-game",
        "roots": {"workspace_root": str(folder), "repo_roots": []},
        "created_at": "2026-01-15T10:00:00Z",
        "updated_at": "2026-01-15T12:00:00Z",
    }
    saved = answer_payload(
        service.handle_line(
            request(
                "workspace.save_config",
                {
                    "config": config,
                    "current_roots": None,
                    "root_confirmation_id": confirmed["root_confirmation_id"],
                },
            )
        )
    )
    assert saved["workspace_id"] == str(WS)

    valid = answer_payload(
        service.handle_line(request("workspace.validate", {"workspace_id": str(WS)}))
    )
    assert valid["health"] == "valid"

    loaded = answer_payload(
        service.handle_line(request("workspace.get_config", {"workspace_id": str(WS)}))
    )
    assert loaded["roots"]["workspace_root"] == str(folder)

    probed = answer_payload(
        service.handle_line(request("workspace.git_status", {"workspace_id": str(WS)}))
    )
    assert probed["workspace_id"] == str(WS)
    assert probed["state"] in ("not_a_repo", "git_absent", "valid")


def test_save_without_confirmation_is_invalid_request(tmp_path) -> None:
    folder = tmp_path / "game"
    folder.mkdir()
    service = BridgeService(controller(tmp_path))
    negotiate(service)
    # A root transition without confirmation never reaches the store: the P1
    # envelope itself refuses it as invalid_request.
    raw = json.dumps(
        {
            "kind": "request",
            "protocol": "studio.local/v1",
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-21T00:00:00Z",
            "command": "workspace.save_config",
            "payload": {
                "config": {
                    "schema_version": 1,
                    "workspace_id": str(WS),
                    "profile": {"profile_id": "main", "server_origin": "https://studio.example"},
                    "project_id": str(PROJECT_ID),
                    "roots": {"workspace_root": str(folder), "repo_roots": []},
                    "created_at": "2026-01-15T10:00:00Z",
                    "updated_at": "2026-01-15T12:00:00Z",
                },
                "current_roots": None,
            },
        }
    )
    answer = service.handle_line(raw)
    assert answer["kind"] == "error"
    assert answer["error"]["code"] == "invalid_request"
    assert str(folder) not in json.dumps(answer)


def test_workspace_commands_need_the_bridge(tmp_path) -> None:
    service = BridgeService(controller(tmp_path, bridge=False))
    negotiate(service)
    # Without a workspace store the daemon grants no workspace.config
    # capability, so the call is refused before any dispatch.
    answer = service.handle_line(request("workspace.validate", {"workspace_id": str(WS)}))
    assert answer["kind"] == "error"
    assert answer["error"]["code"] == "capability_missing"
