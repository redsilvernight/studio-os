"""`skills.check`: read-only Library skill state over the daemon bridge."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.context.library import LibraryContextItem
from studio_client.daemon import skills_bridge
from studio_client.daemon.local_features import LocalFeatureError
from studio_client.daemon.service import BridgeService, DaemonController
from studio_client.errors import AuthenticationError, StudioApiError
from studio_client.skill_sync import apply_skill_sync, plan_skill_sync
from studio_client.tokens import MemoryTokenStore
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.handshake import HandshakeRequest
from studio_contracts.local.skills import SkillsCheckResult

ORIGIN = "https://studio.example"


def _projection(key: str = "studio-git-flow", version: int = 3) -> LibraryContextItem:
    return LibraryContextItem(
        library_kind="skill",
        stable_key=key,
        version=version,
        version_origin="active",
        scope="studio",
        title="Studio Git Flow",
        text="# Git flow\n\nSECRET-BODY-MARKER",
        content_schema="studio.library.skill/v1",
    )


def _controller(tmp_path: Path, home: Path, token: str | None = "tok") -> DaemonController:
    store = MemoryTokenStore()
    if token:
        store.set_token(ORIGIN, token)
    config = ClientConfig(api_base_url=f"{ORIGIN}/api/v1", profile_id="main", machine_id=uuid4())
    return DaemonController(config, data_root=tmp_path, token_store=store, skills_home=lambda: home)


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, result) -> None:
    async def fake(config, token_store):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(skills_bridge, "_fetch", fake)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


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


def test_all_missing_then_in_sync_after_apply(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    projections = [_projection()]
    _patch_fetch(monkeypatch, projections)
    controller = _controller(tmp_path, home)

    before = controller.skills_check()
    assert (before.missing, before.current, before.in_sync) == (2, 0, False)
    assert _snapshot(home) == {}

    apply_skill_sync(plan_skill_sync(home, projections))
    written = _snapshot(home)
    after = controller.skills_check()
    assert (after.missing, after.current, after.in_sync) == (0, 2, True)
    assert _snapshot(home) == written


def test_locally_modified_and_outdated_reported(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    apply_skill_sync(plan_skill_sync(home, [_projection(version=3)]))
    target = home / ".claude" / "skills" / "studio-git-flow" / "SKILL.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
    _patch_fetch(monkeypatch, [_projection(version=3)])
    result = _controller(tmp_path, home).skills_check()
    assert result.locally_modified == 1 and not result.in_sync

    _patch_fetch(monkeypatch, [_projection(version=4)])
    result = _controller(tmp_path, home).skills_check()
    assert result.outdated + result.locally_modified >= 1 and not result.in_sync


def test_served_over_bridge_without_path_or_content(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _patch_fetch(monkeypatch, [_projection()])
    service = BridgeService(_controller(tmp_path, home))
    _negotiate(service, ["daemon.control", "skills.read"])
    answer = service.handle_line(_line("skills.check", {}))
    assert answer["kind"] == "response", answer
    raw = json.dumps(answer, default=str)
    assert "SECRET-BODY-MARKER" not in raw
    assert str(tmp_path) not in raw and "SKILL.md" not in raw
    SkillsCheckResult.model_validate(answer["payload"])


def test_denied_without_capability(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _patch_fetch(monkeypatch, [_projection()])
    service = BridgeService(_controller(tmp_path, home))
    _negotiate(service, ["daemon.control"])
    answer = service.handle_line(_line("skills.check", {}))
    assert answer["kind"] != "response", answer


def test_handshake_offers_skills_read(tmp_path: Path) -> None:
    service = BridgeService(_controller(tmp_path, tmp_path))
    answer = _negotiate(service, ["daemon.control", "skills.read"])
    assert "skills.read" in json.dumps(answer)


def test_token_absent(tmp_path: Path) -> None:
    with pytest.raises(LocalFeatureError) as err:
        _controller(tmp_path, tmp_path, token=None).skills_check()
    assert err.value.error.code.value == "secret_absent"


@pytest.mark.parametrize(
    ("exc", "code", "retryable"),
    [
        (AuthenticationError(401, "unauthorized", "no"), "secret_revoked", False),
        (StudioApiError(503, "down", "down"), "internal_error", True),
    ],
)
def test_upstream_errors_are_mapped(tmp_path: Path, monkeypatch, exc, code, retryable) -> None:
    _patch_fetch(monkeypatch, exc)
    with pytest.raises(LocalFeatureError) as err:
        _controller(tmp_path, tmp_path).skills_check()
    assert err.value.error.code.value == code
    assert err.value.error.retryable is retryable
    assert str(tmp_path) not in err.value.error.message
