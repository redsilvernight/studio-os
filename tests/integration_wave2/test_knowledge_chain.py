from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from studio_client.daemon.service import BridgeService
from studio_contracts.local.graph import GraphPage

from tests.integration_wave2.conftest import (
    DESKTOP_CAPABILITIES,
    WORKSPACE_ID,
    bridge_request,
    build_workspace,
    controller,
    make_registry,
    negotiate,
    wait_for,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "contracts" / "local" / "schemas"


def _validate(instance: object, schema_name: str) -> None:
    import jsonschema

    schema = json.loads((SCHEMA_DIR / f"{schema_name}.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance, schema)


def _status(service: BridgeService, workspace_id: str = str(WORKSPACE_ID)) -> dict:
    return service.handle_line(bridge_request("knowledge.status", {"workspace_id": workspace_id}))


@pytest.fixture
def knowledge_only(tmp_path: Path) -> tuple[BridgeService, object]:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    service = BridgeService(controller_)
    negotiate(service, DESKTOP_CAPABILITIES)
    try:
        yield service, workspace
    finally:
        registry.stop()


def test_a_workspace_vault_reaches_the_graph_page(knowledge_only) -> None:
    service, workspace = knowledge_only
    assert wait_for(lambda: _status(service)["payload"]["state"] == "ready"), _status(service)
    payload = _status(service)["payload"]
    assert payload["workspace_id"] == str(WORKSPACE_ID)
    assert payload["canonical_source"] == "markdown_files"
    assert payload["provider"]["provider_id"] == "markdown-files"
    _validate(payload, "KnowledgeStatus")

    page = service.handle_line(
        bridge_request("knowledge.graph_page", {"workspace_id": str(WORKSPACE_ID), "limit": 100})
    )
    assert page["kind"] == "response", page
    graph = GraphPage.model_validate(page["payload"])
    assert graph.source.kind == "knowledge"
    assert graph.source.workspace_id == WORKSPACE_ID
    assert graph.nodes, "a populated vault yields knowledge nodes"
    assert any(node.kind == "document" for node in graph.nodes)
    assert all(
        node.uri is None or node.uri.startswith("studio-local://knowledge/") for node in graph.nodes
    )
    _validate(page["payload"], "GraphPage")

    document_uri = next(node.uri for node in graph.nodes if node.kind == "document")
    document = service.handle_line(
        bridge_request("knowledge.get_document", {"uri": document_uri, "max_bytes": 4096})
    )
    assert document["kind"] == "response", document
    assert document["payload"]["markdown"]
    _validate(document["payload"], "KnowledgeDocument")


def test_a_search_returns_contract_shaped_hits(knowledge_only) -> None:
    service, _ = knowledge_only
    assert wait_for(lambda: _status(service)["payload"]["state"] == "ready")
    answer = service.handle_line(
        bridge_request(
            "knowledge.search", {"workspace_id": str(WORKSPACE_ID), "query": "Combat", "limit": 10}
        )
    )
    assert answer["kind"] == "response", answer
    assert answer["payload"]["index_state"] == "ready"
    assert answer["payload"]["hits"]
    _validate(answer["payload"], "KnowledgeSearchResult")


def test_a_fresh_workspace_initializes_the_vault_without_manual_filesystem_steps(
    tmp_path: Path,
) -> None:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    shutil.rmtree(workspace.vault)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    service = BridgeService(controller_)
    negotiate(service, DESKTOP_CAPABILITIES)
    try:
        first = service.handle_line(
            bridge_request(
                "knowledge.init_vault",
                {"workspace_id": str(WORKSPACE_ID), "confirmed": True},
            )
        )
        assert first["kind"] == "response", first
        assert first["payload"]["state_before"] == "missing"
        assert "README.md" in first["payload"]["created"]
        assert workspace.vault.joinpath("README.md").is_file()

        second = service.handle_line(
            bridge_request(
                "knowledge.init_vault",
                {"workspace_id": str(WORKSPACE_ID), "confirmed": True},
            )
        )
        assert second["kind"] == "response", second
        assert second["payload"]["state_before"] == "studios_vault"
        assert second["payload"]["created"] == []

        rebuilt = service.handle_line(
            bridge_request(
                "knowledge.reindex",
                {"workspace_id": str(WORKSPACE_ID), "mode": "full_rebuild"},
            )
        )
        assert rebuilt["kind"] == "response", rebuilt
        assert wait_for(lambda: _status(service)["payload"]["state"] == "ready")
    finally:
        registry.stop()


def test_vault_initialization_refuses_a_link_outside_the_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace = build_workspace(workspace_root, knowledge=True, code_graph=False)
    shutil.rmtree(workspace.vault)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, workspace.vault, target_is_directory=True)
    except OSError as error:
        if os.name != "nt":
            pytest.skip(f"directory symlinks are unavailable on this machine: {error}")
        junction = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(workspace.vault), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip("directory links and junctions are unavailable on this machine")
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    service = BridgeService(controller_)
    negotiate(service, DESKTOP_CAPABILITIES)
    try:
        answer = service.handle_line(
            bridge_request(
                "knowledge.init_vault",
                {"workspace_id": str(WORKSPACE_ID), "confirmed": True},
            )
        )
        assert answer["kind"] == "error", answer
        assert answer["error"]["code"] == "invalid_request"
        assert not list(outside.iterdir())
    finally:
        registry.stop()


def test_d_an_inaccessible_vault_reports_unavailable_without_leaking_a_path(
    tmp_path: Path,
) -> None:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    shutil.rmtree(workspace.vault)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    service = BridgeService(controller_)
    negotiate(service, DESKTOP_CAPABILITIES)
    try:
        answer = _status(service)
        assert answer["kind"] == "response", answer
        assert answer["payload"]["state"] == "unavailable", answer["payload"]
        message = answer["payload"]["error"]["message"]
        assert str(tmp_path) not in message
        _validate(answer["payload"], "KnowledgeStatus")
    finally:
        registry.stop()


def test_k_an_unknown_workspace_is_a_bounded_error(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    service = BridgeService(controller_)
    negotiate(service, DESKTOP_CAPABILITIES)
    unknown = "99999999-9999-4999-8999-999999999999"
    try:
        answer = _status(service, unknown)
        assert answer["kind"] == "response", answer
        assert answer["payload"]["state"] == "unavailable"
        assert answer["payload"]["error"]["code"] == "workspace_config_missing"
        assert str(tmp_path) not in json.dumps(answer["payload"])

        page = service.handle_line(
            bridge_request("knowledge.graph_page", {"workspace_id": unknown})
        )
        assert page["kind"] == "error", page
        assert page["error"]["code"] == "feature_disabled"
    finally:
        registry.stop()


def test_knowledge_is_not_served_without_the_feature(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=False, code_graph=False)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    service = BridgeService(controller_)
    negotiate(service, DESKTOP_CAPABILITIES)
    try:
        answer = _status(service)
        assert answer["kind"] == "response", answer
        assert answer["payload"]["state"] == "disabled", answer["payload"]
        assert answer["payload"]["error"]["code"] == "feature_disabled"
    finally:
        registry.stop()
