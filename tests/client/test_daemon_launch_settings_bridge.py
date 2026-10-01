"""`launch.get_settings` / `launch.save_settings`: the owner's local launch opt-in."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from studio_client.config import ClientConfig
from studio_client.daemon.launch_settings_bridge import (
    SETTINGS_FILE,
    effective_launch_config,
    load_launch_settings,
)
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.daemon.service import BridgeService, DaemonController
from studio_client.tokens import MemoryTokenStore
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.handshake import HandshakeRequest
from studio_contracts.local.launch import LaunchSettingsSaveRequest, LaunchSettingsView

ORIGIN = "https://studio.example"


def _config(**extra) -> ClientConfig:
    return ClientConfig(
        api_base_url=f"{ORIGIN}/api/v1", profile_id="main", machine_id=uuid4(), **extra
    )


def _controller(tmp_path: Path, **extra) -> DaemonController:
    return DaemonController(_config(**extra), data_root=tmp_path, token_store=MemoryTokenStore())


def _save(opt_in=True, max_concurrent=2, harnesses=("claude-code",), confirmed=True) -> dict:
    return {
        "opt_in": opt_in,
        "max_concurrent": max_concurrent,
        "allowed_harnesses": list(harnesses),
        "confirmed": confirmed,
    }


def _line(command: str, payload: dict) -> str:
    return BridgeRequest.model_validate(
        {
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-21T00:00:00Z",
            "command": command,
            "payload": payload,
        }
    ).model_dump_json()


def _negotiate(service: BridgeService, capabilities: list[str]) -> dict:
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
    return service.handle_line(_line("runtime.handshake", payload.model_dump(mode="json")))


def test_defaults_are_closed(tmp_path: Path) -> None:
    view = _controller(tmp_path).launch_settings()
    assert (view.opt_in, view.max_concurrent, view.allowed_harnesses) == (False, 1, [])
    assert not (tmp_path / SETTINGS_FILE).exists()


def test_save_then_get_roundtrip_and_effective_config(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    saved = controller.save_launch_settings(LaunchSettingsSaveRequest(**_save()))
    assert saved.opt_in and saved.allowed_harnesses == ["claude-code"]
    assert controller.launch_settings().max_concurrent == 2
    effective = effective_launch_config(controller.config, tmp_path)
    assert effective.launch_opt_in is True
    assert effective.max_concurrent_launches == 2
    assert effective.launch_allowed_harnesses == ("claude-code",)
    assert controller.config.launch_opt_in is False


def test_unknown_harness_refused_and_nothing_written(tmp_path: Path) -> None:
    with pytest.raises(LocalFeatureError) as err:
        _controller(tmp_path).save_launch_settings(
            LaunchSettingsSaveRequest(**_save(harnesses=("rm-rf",)))
        )
    assert err.value.error.code.value == "invalid_request"
    assert not (tmp_path / SETTINGS_FILE).exists()


@pytest.mark.parametrize("content", ["not json", '{"opt_in": true}', '{"opt_in": "yes"}'])
def test_unreadable_file_fails_closed(tmp_path: Path, content: str) -> None:
    (tmp_path / SETTINGS_FILE).write_text(content, encoding="utf-8")
    config = _config(launch_opt_in=True, launch_allowed_harnesses=("codex",))
    settings = load_launch_settings(config, tmp_path)
    assert settings.opt_in is False and settings.allowed_harnesses == []


def test_config_defaults_apply_without_file(tmp_path: Path) -> None:
    config = _config(
        launch_opt_in=True, max_concurrent_launches=3, launch_allowed_harnesses=("codex",)
    )
    settings = load_launch_settings(config, tmp_path)
    assert (settings.opt_in, settings.max_concurrent, settings.allowed_harnesses) == (
        True,
        3,
        ["codex"],
    )


def test_served_over_bridge_without_path(tmp_path: Path) -> None:
    service = BridgeService(_controller(tmp_path))
    _negotiate(service, ["daemon.control", "launch.settings"])
    saved = service.handle_line(_line("launch.save_settings", _save()))
    assert saved["kind"] == "response", saved
    fetched = service.handle_line(_line("launch.get_settings", {}))
    assert fetched["kind"] == "response", fetched
    view = LaunchSettingsView.model_validate(fetched["payload"])
    assert view.opt_in and view.allowed_harnesses == ["claude-code"]
    assert str(tmp_path) not in json.dumps(fetched, default=str)


def test_unconfirmed_save_refused_by_contract() -> None:
    with pytest.raises(ValidationError):
        LaunchSettingsSaveRequest(**_save(confirmed=False))


def test_denied_without_capability(tmp_path: Path) -> None:
    service = BridgeService(_controller(tmp_path))
    _negotiate(service, ["daemon.control"])
    for command, payload in (("launch.get_settings", {}), ("launch.save_settings", _save())):
        assert service.handle_line(_line(command, payload))["kind"] != "response"
    assert not (tmp_path / SETTINGS_FILE).exists()


def test_handshake_offers_launch_settings(tmp_path: Path) -> None:
    answer = _negotiate(BridgeService(_controller(tmp_path)), ["daemon.control", "launch.settings"])
    assert "launch.settings" in json.dumps(answer)
