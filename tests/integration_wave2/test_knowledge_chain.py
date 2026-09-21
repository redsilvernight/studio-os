from __future__ import annotations

import json
import shutil
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
