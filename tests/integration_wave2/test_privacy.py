from __future__ import annotations

import json
import re
from pathlib import Path

from studio_client.daemon.service import BridgeService

from tests.integration_wave2.conftest import (
    DESKTOP_CAPABILITIES,
    WORKSPACE_ID,
    bridge_request,
    build_workspace,
    controller,
    make_registry,
    negotiate,
)

_ABSOLUTE_PATH = re.compile(
    r"""(?:^|[\s"'(])[A-Za-z]:[\\/]|\b/(?:home|users|root)/""", re.IGNORECASE
)


async def test_local_graph_sources_never_upload_anything(tmp_path: Path) -> None:
    from tests.code_graph.support import FakeProvider
    from tests.integration_wave2.test_code_chain import _service

    workspace = build_workspace(tmp_path, knowledge=True, code_graph=True)
    registry = make_registry(
        [workspace.config], tmp_path / "cache", service=_service(tmp_path, FakeProvider())
    )
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        await registry.wait_idle()
        service = BridgeService(controller_)
        negotiate(service, DESKTOP_CAPABILITIES)

        answers = [
            service.handle_line(
                bridge_request("knowledge.status", {"workspace_id": str(WORKSPACE_ID)})
            ),
            service.handle_line(
                bridge_request("knowledge.graph_page", {"workspace_id": str(WORKSPACE_ID)})
            ),
            service.handle_line(
                bridge_request("code_graph.status", {"workspace_id": str(WORKSPACE_ID)})
            ),
            service.handle_line(
                bridge_request("code_graph.graph_page", {"workspace_id": str(WORKSPACE_ID)})
            ),
        ]
        assert all(answer["kind"] == "response" for answer in answers), answers

        serialized = json.dumps(answers)
        assert not _ABSOLUTE_PATH.search(serialized), serialized[:500]
        assert "graphify-out" not in serialized
        assert "graph.json" not in serialized

        assert not (tmp_path / "outbox").exists(), "the local features enqueue nothing"
        databases = list(tmp_path.rglob("*.sqlite3"))
        assert all("cache" in path.parts for path in databases), (
            f"only derived, rebuildable indexes exist: {databases}"
        )
    finally:
        registry.stop()


async def test_the_vault_files_are_never_rewritten_by_a_query(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        before = {path: path.read_bytes() for path in sorted(workspace.vault.rglob("*.md"))}
        service = BridgeService(controller_)
        negotiate(service, DESKTOP_CAPABILITIES)
        service.handle_line(
            bridge_request("knowledge.graph_page", {"workspace_id": str(WORKSPACE_ID)})
        )
        after = {path: path.read_bytes() for path in sorted(workspace.vault.rglob("*.md"))}
        assert before == after, "canonical Markdown is read-only for the daemon"
    finally:
        registry.stop()
